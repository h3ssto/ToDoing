"""Repo growth over months of use, real git. `python tests/bench_git.py [days] [syncs_per_day] [edits_per_sync]`
Compares: our append-only log at several COMPACT_AFTER values vs a naive 'rewrite pretty JSON per sync'."""
import asyncio, json, random, sys, time, tempfile, shutil, pathlib
HERE = pathlib.Path(__file__).parent
sys.path[:0] = [str(HERE), str(HERE.parent / "web" / "py")]
from localgit import LocalGit
from ghtodo import logfmt
from ghtodo.app import App
from ghtodo.model import live_items
from ghtodo.sync import sync
import bench_core as bc

WORDS = bc.WORDS


def workload(ws, lid, r, edits):
    """realistic mix: mostly edits/ticks, some adds, rare deletes"""
    for _ in range(edits):
        items = live_items(ws.lists[lid]); k = r.random()
        if k < .25 or not items: ws.add_item(lid, " ".join(r.choices(WORDS, k=r.randrange(2, 7))), r.choice(items)["id"] if items and r.random() < .3 else None)
        elif k < .70:
            it = r.choice(items); ws.touch(it, text=it["text"] + "\n" + " ".join(r.choices(WORDS, k=r.randrange(2, 6))))
        elif k < .95: it = r.choice(items); ws.touch(it, done=not it["done"])
        else: ws.delete_item(ws.lists[lid], r.choice(items))


async def naive_sync(gh, ws, st):
    """What a straightforward implementation does: whole pretty-printed JSON per list, rewritten each sync."""
    files = {f"lists/{l}.json": json.dumps({"name": v["name"], "items": sorted(v["items"].values(), key=lambda i: i["id"])}, indent=1)
             for l, v in ws.lists.items()}
    _, ref = await gh("GET", "x/git/ref/heads/main", None); head = ref["object"]["sha"]
    _, c = await gh("GET", f"x/git/commits/{head}", None); tree = []
    for p, t in files.items():
        _, b = await gh("POST", "x/git/blobs", {"content": t, "encoding": "utf-8"}); tree.append({"path": p, "mode": "100644", "type": "blob", "sha": b["sha"]})
    _, t = await gh("POST", "x/git/trees", {"base_tree": c["tree"]["sha"], "tree": tree})
    _, nc = await gh("POST", "x/git/commits", {"message": "sync", "tree": t["sha"], "parents": [head]})
    await gh("PATCH", "x/git/refs/heads/main", {"sha": nc["sha"], "force": False})


async def simulate(name, days, spd, edits, start_items=300, seed=3):
    r = random.Random(seed); bc.R.seed(seed)
    tmp = tempfile.mkdtemp(); gh = LocalGit(tmp); app = App()
    ws, lid, _ = bc.make_ws(start_items); app.ws = ws
    st = {"repo": "u/r", "branch": "main", "commit": None, "files": {}}
    rows, t_sync = [], []
    for day in range(1, days + 1):
        for _ in range(spd):
            workload(app.ws, lid, r, edits)
            gh.reset_counters(); s = time.perf_counter()
            await (naive_sync(gh, app.ws, st) if name == "naive-json" else sync(gh, app, st))
            t_sync.append((time.perf_counter() - s) * 1000)
        if day % max(1, days // 6) == 0 or day == days:
            rows.append(dict(day=day, commits=gh.n_commits(), repo_kb=gh.disk_bytes() / 1024,
                             api_calls=len(gh.calls), kb_down=gh.bytes_down / 1024, kb_up=gh.bytes_up / 1024))
    shutil.rmtree(tmp, ignore_errors=True)
    return rows, sum(t_sync) / len(t_sync)


async def main(days=180, spd=2, edits=8):
    out = {}
    for name, comp in [("log@50", 50), ("log@200", 200), ("log@1000", 1000), ("log@never", 10**9), ("naive-json", None)]:
        if comp: logfmt.COMPACT_AFTER = comp
        rows, avg = await simulate(name, days, spd, edits)
        out[name] = rows
        print(f"{name:11} commits={rows[-1]['commits']:4} repo={rows[-1]['repo_kb']:8.0f} KB  "
              f"last-sync: {rows[-1]['api_calls']} calls ↓{rows[-1]['kb_down']:.0f}KB ↑{rows[-1]['kb_up']:.0f}KB  avg sync {avg:.0f} ms", flush=True)
    json.dump(out, open("/tmp/bench_git.json", "w"))

if __name__ == "__main__":
    asyncio.run(main(*[int(x) for x in sys.argv[1:]]))
