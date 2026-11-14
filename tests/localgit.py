"""A *real* git repository behind the subset of the GitHub Git Data API that sync.py uses.
Every SHA, tree and commit is produced by the git CLI, so the sync logic is exercised against real
git semantics (content-addressed blobs, non-fast-forward rejection, ...). No network, no container needed.

Usage: gh = LocalGit(tmpdir); await sync(gh, app, state)   # gh is the `http` callable
"""
import base64, os, subprocess, tempfile, time

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


class LocalGit:
    def __init__(self, path, latency_ms=0, empty=False):
        self.path, self.latency = str(path), latency_ms / 1000
        self.env = {**os.environ, "GIT_DIR": self.path, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null"}
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", self.path], check=True, env=self.env)
        self.git("hash-object", "-t", "tree", "-w", "--stdin", inp=b"")
        if not empty:                      # empty=True mimics 'Create repository' without a README: no commits at all
            c = self.git("commit-tree", EMPTY_TREE, "-m", "init").strip()
            self.git("update-ref", "refs/heads/main", c)
        self.calls, self.bytes_up, self.bytes_down = [], 0, 0

    def git(self, *a, inp=None, env=None):
        r = subprocess.run(["git", *a], input=inp, capture_output=True, env=env or self.env)
        if r.returncode:
            raise RuntimeError(f"git {a}: {r.stderr.decode()}")
        return r.stdout.decode() if not a[0] == "cat-file" else r.stdout

    # ---- helpers for tests -------------------------------------------
    def head(self): return self.git("rev-parse", "refs/heads/main").strip()
    def n_commits(self): return int(self.git("rev-list", "--count", "refs/heads/main"))
    def disk_bytes(self, gc=True):
        if gc:
            self.git("gc", "-q", "--aggressive", "--prune=now")
        out = self.git("count-objects", "-v")
        d = dict(l.split(": ") for l in out.strip().split("\n"))
        return (int(d["size"]) + int(d["size-pack"])) * 1024
    def file_at_head(self, p): return self.git("cat-file", "blob", f"{self.head()}:{p}").decode()
    def reset_counters(self): self.calls, self.bytes_up, self.bytes_down = [], 0, 0

    def truncate_history(self, message="truncate history"):
        """Squash all history into ONE orphan commit and force the ref (what a 'squash' policy does)."""
        tree = self.git("rev-parse", f"{self.head()}^{{tree}}").strip()
        c = self.git("commit-tree", tree, "-m", message).strip()
        self.git("update-ref", "refs/heads/main", c)

    # ---- the `http` callable ------------------------------------------
    async def __call__(self, method, url, body):
        if self.latency: time.sleep(self.latency)
        self.calls.append((method, url.split("/git/")[-1].split("?")[0].split("/")[0]))
        self.bytes_up += len(repr(body)) if body else 0
        if "/contents/" in url and method == "PUT":
            st, out = self._put_contents(url.split("/contents/")[-1], body)
        else:
            st, out = self._route(method, url.split("/git/")[-1], body)
        self.bytes_down += len(repr(out))
        return st, out

    def _put_contents(self, path, body):
        """Contents API: creates the first commit on an empty repo."""
        if subprocess.run(["git", "rev-parse", "-q", "--verify", "refs/heads/main"], env=self.env, capture_output=True).returncode == 0:
            return 422, {"message": "sha required"}
        blob = self.git("hash-object", "-w", "--stdin", inp=base64.b64decode(body["content"])).strip()
        tree = self.git("mktree", inp=f"100644 blob {blob}\t{path}\n".encode()).strip()
        self.git("update-ref", "refs/heads/main", self.git("commit-tree", tree, "-m", body["message"]).strip())
        return 201, {}

    def _route(self, m, u, body):
        if u.startswith("ref/heads/"):
            r = subprocess.run(["git", "rev-parse", "-q", "--verify", "refs/heads/" + u[10:]], env=self.env, capture_output=True)
            if r.returncode: return 404, {"message": "Not Found"}
            return 200, {"object": {"sha": r.stdout.decode().strip()}}
        if u.startswith("trees/") and m == "GET":
            sha = u[6:].split("?")[0]
            ents = []
            for ln in self.git("ls-tree", "-r", sha).splitlines():
                meta, path = ln.split("\t", 1); mode, typ, s = meta.split()
                ents.append({"path": path, "type": typ, "sha": s, "mode": mode})
            return 200, {"tree": ents}
        if u.startswith("blobs/") and m == "GET":
            return 200, {"content": base64.b64encode(self.git("cat-file", "blob", u[6:])).decode(), "encoding": "base64"}
        if u == "blobs":
            s = self.git("hash-object", "-w", "--stdin", inp=body["content"].encode()).strip()
            return 201, {"sha": s}
        if u.startswith("commits/"):
            return 200, {"sha": u[8:], "tree": {"sha": self.git("rev-parse", f"{u[8:]}^{{tree}}").strip()}}
        if u == "trees":
            with tempfile.NamedTemporaryFile() as idx:
                env = {**self.env, "GIT_INDEX_FILE": idx.name}
                os.unlink(idx.name)
                self.git("read-tree", body["base_tree"], env=env)
                lines = "".join(f"{e['mode'] if e['sha'] else 0} {e['sha'] or '0'*40}\t{e['path']}\n" for e in body["tree"])
                self.git("update-index", "--index-info", inp=lines.encode(), env=env)
                return 201, {"sha": self.git("write-tree", env=env).strip()}
        if u == "commits":
            args = ["commit-tree", body["tree"], "-m", body["message"]]
            for p in body["parents"]: args += ["-p", p]
            return 201, {"sha": self.git(*args).strip()}
        if u.startswith("refs/heads/"):
            ref = "refs/heads/" + u[11:]; cur = self.git("rev-parse", ref).strip()
            if not body.get("force"):
                r = subprocess.run(["git", "merge-base", "--is-ancestor", cur, body["sha"]], env=self.env)
                if r.returncode: return 422, {"message": "Update is not a fast forward"}
            self.git("update-ref", ref, body["sha"], cur)       # compare-and-swap
            return 200, {}
        return 404, {"message": u}
