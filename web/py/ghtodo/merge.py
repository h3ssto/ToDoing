"""Three-way merge of workspaces (base = last synced snapshot).

Policy (see PLAN.md §5):
  * merge per list file, per item id, per field
  * one side changed -> take it; both same -> take it
  * `text`: line-level 3-way merge; overlapping edits -> CONFLICT
  * structural/flag fields (parent,pos,done,color): last-writer-wins by `updated`
  * edit vs delete -> edit wins (item is resurrected) and a note lands in Conflicts
  * CONFLICT = remote value stays in place, BOTH sides are copied to the
    "⚠ Conflicts" list; resolving keeps one and removes the pair.
"""
from __future__ import annotations

import difflib
from .model import Workspace, new_item, now, CONFLICTS_ID, between, live_items

FIELDS = ("parent", "pos", "text", "done", "color", "hidden")


def _v(i, f):
    return i.get(f, False) if f == "hidden" else i[f]


def merge3_text(base: str, ours: str, theirs: str):
    """-> (merged, conflict: bool)"""
    if ours == theirs or theirs == base:
        return ours, False
    if ours == base:
        return theirs, False
    b, o, t = base.split("\n"), ours.split("\n"), theirs.split("\n")

    def hunks(x):
        sm = difflib.SequenceMatcher(None, b, x, autojunk=False)
        return [(i1, i2, x[j1:j2]) for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal"]

    ho, ht = hunks(o), hunks(t)
    for a1, a2, _ in ho:
        for c1, c2, _ in ht:
            # overlap, or touching inserts at the same spot
            if a1 < c2 and c1 < a2 or (a1 == a2 == c1) or (c1 == c2 == a1) or (a1 == c1):
                return ours, True
    out, pos = [], 0
    for i1, i2, new in sorted(ho + ht, key=lambda h: (h[0], h[1])):
        out += b[pos:i1] + new
        pos = i2
    out += b[pos:]
    return "\n".join(out), False


def _conflict_pair(ws: Workspace, list_id: str, item_id: str, field: str, ours, theirs, note=""):
    c = ws.conflicts_list()
    for side, val in (("ours", ours), ("theirs", theirs)):
        it = new_item(val if isinstance(val, str) else str(val))
        it["conflict"] = {"list": list_id, "item": item_id, "field": field, "side": side, "note": note}
        # keep order: pos after the last conflict item
        last = max((i["pos"] for i in c["items"].values()), default=None)
        it["pos"] = between(last, None)
        c["items"][it["id"]] = it


def _conflict_note(ws: Workspace, list_id, item_id, note):
    c = ws.conflicts_list()
    it = new_item(note)
    it["conflict"] = {"list": list_id, "item": item_id, "field": "note", "side": "info", "note": ""}
    it["pos"] = between(max((i["pos"] for i in c["items"].values()), default=None), None)
    c["items"][it["id"]] = it


def merge_workspaces(base: Workspace, ours: Workspace, theirs: Workspace) -> tuple[Workspace, int]:
    """-> (merged, number_of_conflicts)"""
    out = Workspace()
    n_conf = 0
    origin = {i["id"]: i for l in base.lists.values() for i in l["items"].values() if not i.get("deleted")}   # pre-move versions
    # list order: theirs, then our new lists
    out.order = list(theirs.order) + [i for i in ours.order if i not in theirs.order]

    for lid in sorted(set(base.lists) | set(ours.lists) | set(theirs.lists)):
        if lid == CONFLICTS_ID:
            continue
        b, o, t = (w.lists.get(lid) for w in (base, ours, theirs))
        if o is None and t is None:
            continue
        if t is None:                      # remote deleted list (we never delete lists yet)
            out.lists[lid] = o
            continue
        if o is None:
            out.lists[lid] = t
            continue
        merged = {"id": lid, "name": t["name"] if (o["name"] == (b or o)["name"]) else o["name"],
                  "items": {}, "links": {}}
        bh, oh, th = (bool((x or {}).get("hidden")) for x in (b, o, t))
        merged["hidden"] = oh if th == bh else th if oh == bh else th      # one-sided change wins; both changed -> theirs
        b_items = b["items"] if b else {}
        for iid in sorted(set(b_items) | set(o["items"]) | set(t["items"])):
            bi, oi, ti = b_items.get(iid), o["items"].get(iid), t["items"].get(iid)
            res, c = _merge_item(out, lid, iid, bi, oi, ti, origin)
            n_conf += c
            if res is not None:
                merged["items"][iid] = res
        b_links = b["links"] if b else {}
        for kid in sorted(set(b_links) | set(o["links"]) | set(t["links"])):
            cands = [x for x in (o["links"].get(kid), t["links"].get(kid)) if x]
            if cands:   # deletion (tombstone) wins if either side tombstoned: strings are cheap to redraw
                dead = [x for x in cands if x.get("deleted")]
                merged["links"][kid] = max(dead, key=lambda x: x["deleted"]) if dead else cands[-1]
        dflag = o.get("deleted") or t.get("deleted")
        if dflag:
            if live_items(merged):             # an edit/new item survived the other device's delete: the list comes back
                _conflict_note(out, lid, None, f"list “{merged['name']}” restored: edited on one device, deleted on another")
                n_conf += 1
            else:
                merged["deleted"] = dflag
        out.lists[lid] = merged

    # conflicts list: union of both sides' entries (by id), we never lose any
    for w in (theirs, ours):
        c = w.lists.get(CONFLICTS_ID)
        if c:
            tgt = out.conflicts_list()
            for k, v in c["items"].items():
                tgt["items"].setdefault(k, v)
    n_conf += _apply_carries(out)
    n_conf += repair(out, origin)
    return out, n_conf


def _apply_carries(out: Workspace) -> int:
    """An item was MOVED to another list on one device while another device edited it: apply those edits to the moved copy
    (3-way per field, text line-merged). If the moved copy is gone, fall back to restoring the edited item where it was."""
    n = 0
    for lid, iid, bi, other, dst_id in getattr(out, "_carry", []):
        seen = {lid}
        while True:                                        # follow the chain of moves (A -> B -> C) to the live copy
            dst = out.lists.get(dst_id, {}).get("items", {}).get(iid)
            if dst is None or not dst.get("deleted") or not dst.get("moved") or dst["moved"] in seen:
                break
            seen.add(dst_id); dst_id = dst["moved"]
        if dst is None or dst.get("deleted"):
            keep = dict(other); keep.pop("deleted", None); keep.pop("moved", None)    # truly gone: restore the edited item
            out.lists[lid]["items"][iid] = keep
            _conflict_note(out, lid, iid, "item restored: edited on one device, moved or deleted on another")
            n += 1
            continue
        res = dict(dst)
        for f in ("text", "done", "color", "hidden"):
            bv, ov, dv = _v(bi, f), _v(other, f), _v(dst, f)
            if ov == bv or ov == dv:
                continue
            if dv == bv:
                res[f] = ov
            elif f == "text":
                merged, conflict = merge3_text(bv, ov, dv)
                if conflict:
                    _conflict_pair(out, dst_id, iid, "text", ov, dv, note="edited on one device, moved on another; texts differ")
                    n += 1
                else:
                    res[f] = merged
            else:
                res[f] = ov if other["updated"] >= dst["updated"] else dv
        if res != dst:
            res["updated"] = max(other["updated"], dst["updated"])
            out.lists[dst_id]["items"][iid] = res
    out.__dict__.pop("_carry", None)
    return n


def repair(ws: Workspace, origin: dict | None = None) -> int:
    """Structural invariants that a field-wise merge can break (found by tests/fuzz.py):
    * live item under a deleted/missing parent (parent deleted on one device, child added on another)
    * parent cycles (A moved under B on one device, B under A on another)
    * strings whose endpoint is dead
    Fix = hoist to the root (nothing is deleted, nothing is lost). Deterministic: same input -> same output."""
    n = 0
    seen: dict[str, tuple] = {}
    for lid, lst in sorted(ws.lists.items()):          # one id must be live in ONE list only (e.g. moved to two lists at once)
        for i in lst["items"].values():
            if i.get("deleted"):
                continue
            prev = seen.get(i["id"])
            if prev is None:
                seen[i["id"]] = (i["updated"], lid, i)
                continue
            cand = (i["updated"], lid, i)
            win, lose = (cand, prev) if (cand[0], cand[1]) > (prev[0], prev[1]) else (prev, cand)
            w, l = win[2], lose[2]
            if l["text"] != w["text"]:                 # lossless: merge both copies' texts against the pre-move version
                base_text = ((origin or {}).get(i["id"]) or {}).get("text", "")
                merged, conflict = merge3_text(base_text, w["text"], l["text"])
                if conflict:
                    _conflict_pair(ws, win[1], i["id"], "text", w["text"], l["text"], note="moved to two lists at once; texts differ")
                    n += 1
                else:
                    w["text"] = merged
                    w["updated"] = max(w["updated"], l["updated"])
            seen[i["id"]] = (w["updated"], win[1], w)
            l["deleted"] = l["updated"] = w["updated"]      # deterministic (not now()): every device must compute the same record
            l["moved"] = win[1]
    alive = {i["id"] for l in ws.lists.values() for i in l["items"].values() if not i.get("deleted")}
    for lst in ws.lists.values():
        items = lst["items"]
        live = {k: i for k, i in items.items() if not i.get("deleted")}
        for i in sorted(live.values(), key=lambda i: i["id"]):
            p = i["parent"]
            if p is not None and p not in live:
                i["parent"] = None; i["updated"] = now()
        for i in sorted(live.values(), key=lambda i: i["id"]):
            seen, cur = {i["id"]}, i
            while cur["parent"] is not None:
                cur = live[cur["parent"]]
                if cur["id"] in seen:           # cycle: cut at the smallest id so every device cuts the same edge
                    cut = live[min(seen)]
                    cut["parent"] = None; cut["updated"] = now()
                    break
                seen.add(cur["id"])
        for l in lst["links"].values():
            if not l.get("deleted") and (l["a"] not in alive or l["b"] not in alive):   # strings may span lists
                l["deleted"] = now()
    return n


def _merge_item(out, lid, iid, bi, oi, ti, origin=None):
    if oi is None and ti is None:
        return None, 0
    if bi is None and oi is not None and ti is not None:
        # present on BOTH sides but not in the base list: the item was moved here on both devices (or moved here and edited).
        # Merge the two copies against the version it had before the move.
        bi = (origin or {}).get(iid)
        if bi is None:                      # no ancestor known: newest wins, the other side's text is kept in Conflicts
            if oi == ti:
                return ti, 0
            win, lose = (oi, ti) if (oi["updated"], oi["text"]) > (ti["updated"], ti["text"]) else (ti, oi)
            if win["text"] != lose["text"]:
                _conflict_pair(out, lid, iid, "text", oi["text"], ti["text"], note="same item added on two devices; texts differ")
                return win, 1
            return win, 0
    if bi is None:                         # added on one side only
        return (oi or ti), 0
    if oi is None or ti is None:
        return (oi or ti), 0
    o_del, t_del = oi.get("deleted"), ti.get("deleted")
    o_chg = any(_v(oi, f) != _v(bi, f) for f in FIELDS)
    t_chg = any(_v(ti, f) != _v(bi, f) for f in FIELDS)
    if o_del and t_del:
        return ti, 0
    if o_del or t_del:
        deleter, other = (oi, ti) if o_del else (ti, oi)
        edited = (t_chg if o_del else o_chg)
        if edited and deleter.get("moved"):
            out.__dict__.setdefault("_carry", []).append((lid, iid, bi, other, deleter["moved"]))   # moved, not deleted: edits follow it
            return deleter, 0
        if edited:                         # edit beats delete: resurrect, keeping BOTH sides' text edits
            keep = dict(other)
            keep.pop("deleted", None)
            merged, conflict = merge3_text(bi["text"], other["text"], deleter["text"])
            if conflict:
                _conflict_pair(out, lid, iid, "text", other["text"], deleter["text"],
                               note="item restored (deleted on another device); texts differ")
            else:
                keep["text"] = merged
                _conflict_note(out, lid, iid, "item restored: edited on one device, deleted on another")
            keep["updated"] = max(oi["updated"], ti["updated"])
            return keep, 1
        return deleter, 0
    res, n = dict(ti), 0
    for f in FIELDS:
        bv, ov, tv = _v(bi, f), _v(oi, f), _v(ti, f)
        if ov == tv or tv == bv:
            res[f] = ov
        elif ov == bv:
            res[f] = tv
        elif f == "text":
            merged, conflict = merge3_text(bv, ov, tv)
            if conflict:
                _conflict_pair(out, lid, iid, f, ov, tv)
                res[f] = tv                # remote stays; ours is preserved in Conflicts
                n += 1
            else:
                res[f] = merged
        else:                              # LWW
            res[f] = ov if oi["updated"] >= ti["updated"] else tv
    if all(_v(res, f) == _v(ti, f) for f in FIELDS):
        return ti, n                       # identical to remote -> no log churn
    res["updated"] = max(oi["updated"], ti["updated"])
    return res, n
