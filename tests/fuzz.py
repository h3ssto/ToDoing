"""Multi-device fuzzer against a real git repo. `python tests/fuzz.py [n_seeds] [rounds] [devices] [first_seed]`

Invariants checked after all devices have gone back online and converged:
  I1 convergence      every device holds exactly the same workspace, equal to what is in git
  I2 integrity        no live item hangs under a missing/deleted parent, no parent cycles, no links to dead items
  I3 no lost items    an item nobody deleted is alive
  I4 no lost edits    every text line any device ever wrote and nobody deliberately removed is still
                      reachable: in its item, in the ⚠ Conflicts list, or the item was deleted
  I5 stability        one more sync round changes nothing (no commits)
"""
import asyncio, random, re, sys, pathlib, tempfile, shutil, json
HERE = pathlib.Path(__file__).parent
sys.path[:0] = [str(HERE), str(HERE.parent / "web" / "py")]
from localgit import LocalGit
from ghtodo.app import App
from ghtodo.sync import sync
from ghtodo.model import Workspace, live_items, COLORS, CONFLICTS_ID


def unrow(line: str) -> str:
    """`  * [x] t5-3` -> `t5-3`: tokens may live in sub-item rows, which move and change indentation."""
    return re.sub(r"^\s*[-*+]\s+\[[ xX]\]\s?", "", line).strip()


def make_deterministic(seed):
    """Seeded ids + logical clock (ties possible) so every failing seed replays exactly."""
    import ghtodo.model as M, ghtodo.merge as G, ghtodo.app as A
    r, clock = random.Random(seed * 7919 + 1), [1_000_000]
    def now(): clock[0] += r.randrange(0, 3); return clock[0]
    nid = lambda: f"{r.getrandbits(40):010x}"
    for mod in (M, G, A):
        if hasattr(mod, "now"): mod.now = now
        if hasattr(mod, "new_id"): mod.new_id = nid


class Dev:
    def __init__(s, name):
        s.name, s.app, s.online = name, App(), True
        s.st = {"repo": "u/r", "branch": "main", "commit": None, "files": {}}


class Sim:
    def __init__(s, seed, n_dev=3, truncate=True):
        s.r = random.Random(seed); s.seed = seed; make_deterministic(seed)
        s.tmp = tempfile.mkdtemp(); s.gh = LocalGit(s.tmp)
        s.devs = [Dev(f"d{i}") for i in range(n_dev)]
        s.tok = 0; s.written, s.removed = set(), set()
        s.created, s.deleted = set(), set(); s.where = {}; s.author = {}; s.deleted_by = {}
        s.truncate = truncate; s.sync_msgs = []

    def newtok(s, it=None, d=None):
        s.tok += 1; t = f"t{s.seed}-{s.tok}"; s.written.add(t); s.where[t] = it; s.author[t] = d.name if d else None; return t

    # ---- random user actions -------------------------------------------
    def act(s, d):
        ws, r = d.app.ws, s.r
        lists = [l for l in ws.lists if l != CONFLICTS_ID]
        if not lists or r.random() < 0.02:
            l = ws.add_list(f"L{r.randrange(99)}"); lists.append(l["id"])
        lst = ws.lists[r.choice(lists)]
        items = live_items(lst)
        op = r.choices(["add", "edit", "toggle", "color", "move", "del", "link", "unlink", "xdrop", "xlink", "row", "rowmove"],
                       [26, 26, 8, 5, 8, 6, 6, 2, 6, 4, 10, 8])[0]
        if op == "add" or not items:
            it = ws.add_item(lst["id"], ""); it["text"] = s.newtok(it["id"], d); s.created.add(it["id"])
            return
        it = r.choice(items)
        if op == "edit":
            lines = it["text"].split("\n"); k = r.random()
            if k < .5: lines.append(s.newtok(it["id"], d))
            elif k < .8: lines.insert(r.randrange(len(lines) + 1), s.newtok(it["id"], d))
            else:
                i = r.randrange(len(lines)); s.removed.add(unrow(lines[i])); lines[i] = s.newtok(it["id"], d)
            ws.touch(it, text="\n".join(lines))
        elif op == "toggle": ws.touch(it, done=not it["done"])
        elif op == "color": ws.touch(it, color=r.choice(COLORS))
        elif op == "move": ws.move(lst, it, r.choice(["up", "down"]))
        elif op == "row":                                              # a new sub-item line (markdown `* [ ] token`)
            ws.add_line(it, s.newtok(it["id"], d))
        elif op == "rowmove" and len(items) > 1:                       # drag a sub-item line to another item's sub-items
            from ghtodo import mdparse as md
            rows = [(i, c) for i in items for kind, v in md.segments(md.split_name(i["text"])[1]) if kind == "check" for c in v]
            if rows:
                src, row = r.choice(rows); ex = md.extract_block(src["text"], row["line"])
                dst = r.choice([i for i in items if i["id"] != src["id"]])
                if ex:
                    rest, block = ex
                    for t in re.findall(r"t\d+-\d+", "\n".join(block)): s.where[t] = dst["id"]
                    ws.touch(src, text=rest); ws.touch(dst, text=md.insert_block(dst["text"], block))

        elif op == "del":
            sub, stack = [], [it]
            while stack:
                x = stack.pop(); sub.append(x["id"])
                stack += [c for c in live_items(lst) if c["parent"] == x["id"]]
            s.deleted.update(sub)
            for x in sub: s.deleted_by.setdefault(x, set()).add(d.name)
            ws.delete_item(lst, it)
        elif op == "link" and len(items) > 1:
            a, b = r.sample(items, 2); k = f"k{r.randrange(10**9)}"; lst["links"][k] = {"id": k, "a": a["id"], "b": b["id"]}
        elif op == "xdrop" and len(lists) > 1:                       # drag an item (+subtree) into another list
            dst = r.choice([l for l in lists if l != lst["id"]])
            ws.drop(it["id"], dst, None)
        elif op == "xlink" and len(lists) > 1:                       # string between items of different lists
            other = r.choice([l for l in lists if l != lst["id"]]); oi = live_items(ws.lists[other])
            if oi:
                b = r.choice(oi); k = f"x{r.randrange(10**9)}"; lst["links"][k] = {"id": k, "a": it["id"], "b": b["id"]}
        elif op == "unlink":
            lk = [l for l in lst["links"].values() if not l.get("deleted")]
            if lk: lk[0]["deleted"] = 1

    async def do_sync(s, d):
        msg = await sync(s.gh, d.app, d.st); s.sync_msgs.append(msg); return msg

    async def run(s, rounds):
        for rd in range(rounds):
            for d in s.r.sample(s.devs, len(s.devs)):
                if s.r.random() < .15: d.online = not d.online          # flaky connectivity
                for _ in range(s.r.randrange(0, 6)): s.act(d)
                if d.online and s.r.random() < .6: await s.do_sync(d)
            if s.truncate and s.r.random() < .08: s.gh.truncate_history()
        for d in s.devs: d.online = True
        s.rounds_to_converge = 0
        for _ in range(8):                                               # converge
            before = s.gh.head(); s.rounds_to_converge += 1
            msgs = [await s.do_sync(d) for d in s.devs]
            if s.gh.head() == before and all(m.startswith("up to date") for m in msgs): break
        errs = s.check()
        head = s.gh.head()                                                # I5 stability
        msgs = [await s.do_sync(d) for d in s.devs]
        if s.gh.head() != head: errs.append("I5 extra sync still produced a commit")
        return errs

    # ---- invariants -----------------------------------------------------
    def check(s):
        errs = []
        canon = lambda ws: json.dumps({k: {"n": v["name"], "i": v["items"], "l": v["links"]} for k, v in sorted(ws.lists.items())}, sort_keys=True)
        remote = Workspace.from_files({p: s.gh.file_at_head(p) for p in s.gh.git("ls-tree", "-r", "--name-only", "main").split()})
        base = canon(remote)
        for d in s.devs:
            if canon(d.app.ws) != base: errs.append(f"I1 {d.name} differs from remote")
        all_live = {i["id"] for l in remote.lists.values() for i in live_items(l)}
        for lid, lst in remote.lists.items():
            live = {i["id"]: i for i in live_items(lst)}
            for i in live.values():
                if i["parent"] is not None and i["parent"] not in live: errs.append(f"I2 orphan {i['id']} in {lid}")
                seen, cur = set(), i
                while cur and cur["parent"] is not None and cur["parent"] in live:
                    if cur["id"] in seen: errs.append(f"I2 cycle at {i['id']}"); break
                    seen.add(cur["id"]); cur = live[cur["parent"]]
            for l in lst["links"].values():
                if not l.get("deleted") and (l["a"] not in all_live or l["b"] not in all_live): errs.append(f"I2 dangling link {l['id']}")
        alive = {i["id"]: i for l in remote.lists.values() for i in live_items(l)}
        for iid in s.created:
            if iid not in alive and iid not in s.deleted: errs.append(f"I3 lost item {iid}")
        corpus = "\n".join(i["text"] for i in alive.values()) + "\n" + "\n".join(
            i["text"] for i in live_items(remote.lists.get(CONFLICTS_ID, {"items": {}})))
        lines = {unrow(l) for l in corpus.split("\n")}
        for t in s.written - s.removed:
            if s.where.get(t) not in alive: continue          # item is dead: text going away is intended
            if s.author.get(t) in s.deleted_by.get(s.where.get(t), ()): continue   # author deleted it themselves
            if t not in lines: errs.append(f"I4 lost edit {t} (item {s.where[t]} text={alive.get(s.where[t],{}).get('text')!r})")
        return errs

    def cleanup(s): shutil.rmtree(s.tmp, ignore_errors=True)


async def main(n_seeds=30, rounds=25, n_dev=3, start=0):
    bad = 0
    for seed in range(start, start + n_seeds):
        sim = Sim(seed, n_dev)
        errs = await sim.run(rounds)
        if errs:
            bad += 1; print(f"seed {seed}: {len(errs)} violations, e.g. {errs[:3]}")
        sim.cleanup()
    print(f"{n_seeds - bad}/{n_seeds} seeds clean")
    return bad

if __name__ == "__main__":
    a = [int(x) for x in sys.argv[1:]]
    sys.exit(1 if asyncio.run(main(*a)) else 0)
