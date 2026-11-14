"""GitHub sync via the Git Data API: ONE commit per sync, however many lists changed.

http: async (method, url, body|None) -> (status:int, json|None)   (injected; pyfetch in the browser)
"""
from __future__ import annotations

import base64
import hashlib

from .merge import merge_workspaces
from .model import Workspace, gc_tombstones

API = "https://api.github.com"
REPO_NAME = "_todoing_data_"
SYNCED = lambda p: p == "ghtodo.json" or (p.startswith("lists/") and p.endswith(".log"))


def blob_sha(text: str) -> str:
    b = text.encode()
    return hashlib.sha1(b"blob %d\0" % len(b) + b).hexdigest()


class SyncError(Exception):
    pass


async def ensure_repo(http, login: str) -> tuple[str, str]:
    """-> (full_name, default_branch). Uses the repo if it exists. A classic token (`repo` scope) can also create it;
    a fine-grained token cannot create user repos, so we tell the user to create it (link in the Connect dialog)."""
    st, d = await http("GET", f"{API}/repos/{login}/{REPO_NAME}", None)
    if st in (403, 404):
        st, d = await http("POST", f"{API}/user/repos", {
            "name": REPO_NAME, "private": True, "auto_init": True,
            "description": "ToDoing data (append-only compressed list logs)"})
        if st >= 300:
            raise SyncError(f"Repo {login}/{REPO_NAME} not found. Create it first "
                            f"(https://github.com/new?name={REPO_NAME}&visibility=private), then connect again.")
    if st >= 300:
        raise SyncError(f"repo setup failed: {st}")
    if not d.get("private"):
        raise SyncError(f"{d['full_name']} is not private; refusing to sync")
    if d.get("size", 1) == 0 and not d.get("default_branch"):
        raise SyncError("repo is empty")
    return d["full_name"], d["default_branch"]


async def _remote_files(http, repo, commit, known: dict[str, str]) -> dict[str, str]:
    st, d = await http("GET", f"{API}/repos/{repo}/git/trees/{commit}?recursive=1", None)
    if st != 200:
        raise SyncError(f"tree: {st}")
    known_by_sha = {blob_sha(t): t for t in known.values()}
    out = {}
    for e in d["tree"]:
        if e["type"] == "blob" and SYNCED(e["path"]):
            if e["sha"] in known_by_sha:
                out[e["path"]] = known_by_sha[e["sha"]]
            else:
                st, b = await http("GET", f"{API}/repos/{repo}/git/blobs/{e['sha']}", None)
                if st != 200:
                    raise SyncError(f"blob: {st}")
                out[e["path"]] = base64.b64decode(b["content"]).decode()
    return out


async def ensure_initialized(http, repo: str, branch: str):
    """A repo made with 'Create repository' (no README ticked) has NO commits and the Git Data API refuses it
    (404/409). The Contents API can create the first commit, so use it once."""
    s, _ = await http("GET", f"{API}/repos/{repo}/git/ref/heads/{branch}", None)
    if s in (404, 409):
        text = "# ghtodo data\n\nManaged by ghtodo. `lists/*.log` are append-only compressed logs; do not edit by hand.\n"
        s, d = await http("PUT", f"{API}/repos/{repo}/contents/README.md", {
            "message": "init ghtodo data", "content": base64.b64encode(text.encode()).decode(), "branch": branch})
        if s >= 300:
            raise SyncError(f"could not initialise empty repo: {s}")


async def sync(http, app, st: dict, retries=3) -> str:
    """st = {"repo","branch","commit","files"} (mutated). Returns a human status line."""
    repo, branch = st["repo"], st["branch"]
    await ensure_initialized(http, repo, branch)
    for _ in range(retries):
        s, ref = await http("GET", f"{API}/repos/{repo}/git/ref/heads/{branch}", None)
        if s in (401, 403):
            raise SyncError("token rejected or expired - sign in again")
        if s != 200:
            raise SyncError(f"ref: {s}")
        head = ref["object"]["sha"]
        base_files = st.get("files", {})
        remote_files = base_files if head == st.get("commit") else await _remote_files(http, repo, head, base_files)
        conflicts = 0
        if remote_files != base_files:
            merged, conflicts = merge_workspaces(Workspace.from_files(base_files), app.ws,
                                                 Workspace.from_files(remote_files))
        else:
            merged = app.ws
        merged.flatten()                                  # an older device may still push nested items
        gc_tombstones(merged)
        new_files = merged.to_files(remote_files)
        changed = {p: t for p, t in new_files.items() if remote_files.get(p) != t}
        if not changed:
            app.ws = merged
            st.update(commit=head, files=remote_files)
            return "up to date" + (f" · {conflicts} conflicts" if conflicts else "")
        s, c = await http("GET", f"{API}/repos/{repo}/git/commits/{head}", None)
        tree = []
        for p, t in changed.items():
            s, b = await http("POST", f"{API}/repos/{repo}/git/blobs", {"content": t, "encoding": "utf-8"})
            if s >= 300:
                raise SyncError(f"blob create: {s}")
            tree.append({"path": p, "mode": "100644", "type": "blob", "sha": b["sha"]})
        s, t = await http("POST", f"{API}/repos/{repo}/git/trees", {"base_tree": c["tree"]["sha"], "tree": tree})
        s, nc = await http("POST", f"{API}/repos/{repo}/git/commits", {
            "message": f"sync: {len(changed)} file(s)" + (f", {conflicts} conflict(s)" if conflicts else ""),
            "tree": t["sha"], "parents": [head]})
        s, _ = await http("PATCH", f"{API}/repos/{repo}/git/refs/heads/{branch}", {"sha": nc["sha"], "force": False})
        if s == 200:
            app.ws = merged
            st.update(commit=nc["sha"], files={**remote_files, **changed})
            return f"synced {len(changed)} file(s)" + (f" · {conflicts} conflict(s) → see ⚠ Conflicts" if conflicts else "")
        # 422 = someone pushed in between -> loop: re-fetch, re-merge
    raise SyncError("gave up after concurrent pushes")
