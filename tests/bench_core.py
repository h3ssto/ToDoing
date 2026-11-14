"""CPU-only benchmarks of the core (no git, no network). Runs under CPython AND Pyodide:
   python tests/bench_core.py            |   node tests/bench_pyodide.mjs
"""
import json, random, time, sys

try:
    from ghtodo import logfmt, merge
    from ghtodo.app import App
except ImportError:
    sys.path[:0] = ["web/py"]
    from ghtodo import logfmt, merge
    from ghtodo.app import App
from ghtodo.model import Workspace

R = random.Random(1)
WORDS = "buy milk call mum review pr fix bug write docs plan trip book flights clean desk ship release test".split()


def make_ws(n, nested=True):
    ws = Workspace(); lid = ws.add_list("L")["id"]; ids = []
    for i in range(n):
        txt = " ".join(R.choices(WORDS, k=R.randrange(2, 6)))
        if R.random() < .3: txt += "\n" + "\n".join(f"* [ ] {R.choice(WORDS)}" for _ in range(R.randrange(1, 4)))
        parent = R.choice(ids) if (nested and ids and R.random() < .4) else None
        ids.append(ws.add_item(lid, txt, parent)["id"])
    return ws, lid, ids


def edit(ws, lid, ids, k):
    for i in R.sample(ids, min(k, len(ids))):
        it = ws.lists[lid]["items"][i]; ws.touch(it, text=it["text"] + "\n" + R.choice(WORDS))


def t(f, reps=3):
    best = 1e9
    for _ in range(reps):
        s = time.perf_counter(); out = f(); best = min(best, time.perf_counter() - s)
    return best * 1000, out


def run(sizes=(100, 1000, 5000, 20000)):
    rows = []
    for n in sizes:
        ws, lid, ids = make_ws(n)
        full = ws.to_files(); path = f"lists/{lid}.log"
        raw_json = len(json.dumps(list(ws.lists[lid]["items"].values()), separators=(",", ":")).encode())
        ms_replay, _ = t(lambda: Workspace.from_files(full))
        base = Workspace.from_files(full)
        import copy
        cur = copy.deepcopy(base); edit(cur, lid, ids, 10)
        ms_delta, newf = t(lambda: cur.to_files(full))
        ours, theirs = copy.deepcopy(base), copy.deepcopy(base); edit(ours, lid, ids, 10); edit(theirs, lid, ids, 10)
        ms_merge, (m, nc) = t(lambda: merge.merge_workspaces(base, ours, theirs), reps=2)
        app = App(ws)
        ms_render, html = (t(lambda: app.list_view(lid), reps=2) if n <= 5000 else (float("nan"), ""))
        rows.append(dict(items=n, snapshot_kb=len(full[path]) / 1024, raw_json_kb=raw_json / 1024,
                         bytes_per_item=len(full[path]) / n, delta_line_bytes=len(newf[path]) - len(full[path]),
                         replay_ms=ms_replay, append_delta_ms=ms_delta, merge3_10v10_ms=ms_merge,
                         render_list_ms=ms_render, html_kb=len(html) / 1024))
    return rows


def run_log(lines=(10, 50, 200, 1000), items=500):
    """cost of replaying a log that has `lines` appended deltas (what compaction bounds)."""
    out = []
    for L in lines:
        ws, lid, ids = make_ws(items); files = ws.to_files(); p = f"lists/{lid}.log"
        cur = ws
        for _ in range(L - 1):
            edit(cur, lid, ids, 5); files = cur.to_files(files)
            files[p] = files[p]  # keep appending (compaction disabled by caller)
        ms, _ = t(lambda: Workspace.from_files(files))
        out.append(dict(log_lines=L, file_kb=len(files[p]) / 1024, replay_ms=ms))
    return out


if __name__ == "__main__":
    logfmt.COMPACT_AFTER = 10 ** 9
    sizes = tuple(int(x) for x in sys.argv[1:]) or (100, 1000, 5000, 20000)
    print(json.dumps({"scaling": run(sizes), "log_length": run_log()}, indent=1))
