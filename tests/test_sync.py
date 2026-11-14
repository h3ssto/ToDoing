import sys, pathlib, asyncio, base64, hashlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web" / "py"))

from ghtodo.app import App
from ghtodo.sync import sync, blob_sha


class FakeGH:
    def __init__(s):
        s.blobs, s.trees, s.commits, s.head, s.n = {}, {}, {}, None, 0
        t = s._tree({}); s.head = s._commit(t, [])
    def _id(s): s.n += 1; return hashlib.sha1(str(s.n).encode()).hexdigest()
    def _tree(s, files): i = s._id(); s.trees[i] = files; return i
    def _commit(s, t, par): i = s._id(); s.commits[i] = {"tree": {"sha": t}, "parents": par}; return i
    async def __call__(s, m, url, body):
        u = url.split("/git/")[-1]
        if u.startswith("ref/"): return 200, {"object": {"sha": s.head}}
        if u.startswith("trees/") and m == "GET":
            f = s.trees[s.commits[u[6:].split("?")[0]]["tree"]["sha"]]
            return 200, {"tree": [{"path": p, "type": "blob", "sha": b} for p, b in f.items()]}
        if u.startswith("blobs/") and m == "GET":
            return 200, {"content": base64.b64encode(s.blobs[u[6:]].encode()).decode()}
        if u == "blobs": i = blob_sha(body["content"]); s.blobs[i] = body["content"]; return 201, {"sha": i}
        if u == "trees":
            f = dict(s.trees[s.commits[s.head]["tree"]["sha"]]) if True else {}
            f.update({e["path"]: e["sha"] for e in body["tree"]}); return 201, {"sha": s._tree(f)}
        if u.startswith("commits/"): return 200, s.commits[u[8:]]
        if u == "commits": return 201, {"sha": s._commit(body["tree"], body["parents"])}
        if u.startswith("refs/"):
            if body["sha"] and s.commits[body["sha"]]["parents"] != [s.head]: return 422, None
            s.head = body["sha"]; return 200, {}


def run(c): return asyncio.run(c)


def test_two_devices():
    gh = FakeGH()
    A, B = App(), App()
    sa = {"repo": "u/r", "branch": "main", "commit": None, "files": {}}
    sb = {"repo": "u/r", "branch": "main", "commit": None, "files": {}}
    A.handle("POST", "/list", {"name": "L"}); lid = A.ws.order[0]
    A.handle("POST", f"/list/{lid}/item", {"text": "t\nx\ny"})
    print(run(sync(gh, A, sa)))
    print(run(sync(gh, B, sb)))
    iid = next(iter(B.ws.lists[lid]["items"]))
    A.handle("POST", f"/item/{iid}", {"text": "t\nA\ny"})
    B.handle("POST", f"/item/{iid}", {"text": "t\nB\ny"})
    commits_before = len(gh.commits)
    print(run(sync(gh, A, sa)))
    print(run(sync(gh, B, sb)))
    assert len(gh.commits) == commits_before + 2          # one commit per sync
    assert len(B.ws.lists["_conflicts"]["items"]) == 2
    print(run(sync(gh, A, sa)))
    assert len(A.ws.lists["_conflicts"]["items"]) == 2    # propagated to A
    assert run(sync(gh, A, sa)) == "up to date"
    # log files only ever grew by appended lines
    p = f"lists/{lid}.log"
    assert sa["files"][p].count("\n") == 2, sa["files"][p].count("\n")

if __name__ == "__main__": test_two_devices(); print("ok")


def test_empty_repo_is_initialised():
    """'Create repository' without README gives a repo with no commits; sync must still work."""
    import tempfile
    from localgit import LocalGit
    gh = LocalGit(tempfile.mkdtemp(), empty=True)
    A = App(); A.handle("POST", "/list", {"name": "L"})
    st = {"repo": "u/r", "branch": "main", "commit": None, "files": {}}
    print(asyncio.run(sync(gh, A, st)))
    assert gh.n_commits() == 2                      # README commit + our first sync
    B = App(); sb = {"repo": "u/r", "branch": "main", "commit": None, "files": {}}
    asyncio.run(sync(gh, B, sb)); assert [l["name"] for l in B.ws.visible_lists()] == ["L"]


def test_auth_failure_message():
    async def deny(m, u, b): return 401, {"message": "Bad credentials"}
    try: asyncio.run(sync(deny, App(), {"repo": "u/r", "branch": "main", "commit": None, "files": {}}))
    except Exception as e: assert "sign in again" in str(e) or "initialise" in str(e), e
