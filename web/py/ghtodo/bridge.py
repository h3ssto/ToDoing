"""Browser glue (runs inside the Pyodide worker). `host` is a small JS object:
host.idbGet(k) / host.idbSet(k, str) / host.idbDel(k)."""
import json

from pyodide.http import pyfetch

from .app import App
from .model import Workspace
from . import share
from . import sync as gsync

S = {"app": None, "host": None, "token": None, "login": None, "sync": {}, "msg": "not signed in"}


async def http(method, url, body):
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if S["token"]:
        h["Authorization"] = f"Bearer {S['token']}"
    kw = {"method": method, "headers": h}
    if body is not None:
        kw["body"] = json.dumps(body)
    r = await pyfetch(url, **kw)
    try:
        return r.status, await r.json()
    except Exception:
        return r.status, None


async def init(host):
    S["host"] = host
    local = await host.idbGet("local")
    ws = Workspace.from_files(json.loads(local)) if local else Workspace()
    S["app"] = App(ws, persist=lambda w: host.idbSet("local", json.dumps(w.to_files())),
                   sync_status=lambda: S["msg"])
    for k in ("token", "login", "sync"):
        v = await host.idbGet(k)
        if v:
            S[k] = json.loads(v)
    S["msg"] = f"signed in as {S['login']}" if S["token"] else "not signed in"
    return bool(S["token"])


def share_key():
    return share.encode(S["token"]) if S["token"] else ""


async def peek(key):
    """Whose account does this key open? (asked before the user confirms joining; nothing is stored)"""
    try:
        tok = share.decode(key)
    except ValueError as e:
        return f"!{e}"
    old, S["token"] = S["token"], tok
    try:
        st, u = await http("GET", "https://api.github.com/user", None)
        return u["login"] if st == 200 and u else f"!GitHub rejected the key ({st})"
    except Exception as e:
        return f"!{e}"
    finally:
        S["token"] = old


async def login(token):
    try:
        token = share.decode(token)
    except ValueError as e:
        S["msg"] = f"not signed in – {e}"
        return S["msg"]
    S["token"] = token
    try:
        st, u = await http("GET", "https://api.github.com/user", None)
        if st != 200:
            raise gsync.SyncError(f"GitHub rejected the token ({st})")
        S["login"] = u["login"]
        repo, branch = await gsync.ensure_repo(http, u["login"])
    except Exception as e:
        S["token"] = None
        S["msg"] = f"not signed in – {e}"
        return S["msg"]
    S["sync"] = {"repo": repo, "branch": branch, "commit": None, "files": {}}
    for k in ("token", "login", "sync"):
        await S["host"].idbSet(k, json.dumps(S[k]))
    warn = " (classic token: consider a fine-grained one limited to this repo)" if token.startswith("ghp_") else ""
    S["msg"] = f"signed in as {u['login']} · {repo}{warn}"
    return await sync()


async def logout():
    for k in ("token", "login", "sync"):
        await S["host"].idbDel(k)
        S[k] = None if k != "sync" else {}
    S["msg"] = "not signed in"


async def sync():
    if not S["token"]:
        return "not signed in"
    try:
        S["msg"] = await gsync.sync(http, S["app"], S["sync"])
        S["app"].dirty = False
        await S["host"].idbSet("sync", json.dumps(S["sync"]))
        await S["host"].idbSet("local", json.dumps(S["app"].ws.to_files()))
    except Exception as e:       # offline etc. -> keep working locally
        S["msg"] = f"sync pending ({e})"
    return S["msg"]


def handle(method, path, params_json):
    return S["app"].handle(method, path, json.loads(params_json))
