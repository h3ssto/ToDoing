"""Data model + on-disk format.

Repo layout (one file per list, so unrelated edits never touch the same blob):

    ghtodo.json            {"v":1,"order":[list ids]}
    lists/<id>.log         append-only log, one zlib+base64 delta per line (see logfmt.py)

Items are a flat record set (parent + fractional `pos`), not a nested JSON
tree. That makes merging "by item id" trivial and moves cheap.
"""
from __future__ import annotations

import json
import secrets
import time

SCHEMA = 1
CONFLICTS_ID = "_conflicts"
COLORS = ["", "red", "orange", "yellow", "green", "blue", "purple"]
TOMBSTONE_TTL_MS = 30 * 24 * 3600 * 1000
_A = "0123456789abcdefghijklmnopqrstuvwxyz"


def new_id() -> str:
    return secrets.token_hex(5)


def now() -> int:
    return int(time.time() * 1000)


def between(a: str | None, b: str | None) -> str:
    """Fractional index strictly between a and b (None = open end)."""
    a = a or ""
    res, i = "", 0
    while True:
        ca = _A.index(a[i]) if i < len(a) else 0
        cb = _A.index(b[i]) if b is not None and i < len(b) else len(_A)
        if ca == cb:
            res += _A[ca]
            i += 1
            continue
        if cb - ca > 1:
            return res + _A[(ca + cb) // 2]
        res += _A[ca]
        i += 1
        b = None  # prefix is now strictly below b; upper bound is open


def new_item(text="", parent=None, pos="i") -> dict:
    t = now()
    return {"id": new_id(), "parent": parent, "pos": pos, "text": text,
            "done": False, "color": "", "created": t, "updated": t}


class Workspace:
    def __init__(self):
        self.order: list[str] = []
        self.lists: dict[str, dict] = {}

    # ---- lists -------------------------------------------------------
    def add_list(self, name: str) -> dict:
        lst = {"id": new_id(), "name": name, "items": {}, "links": {}}
        self.lists[lst["id"]] = lst
        self.order.append(lst["id"])
        return lst

    def conflicts_list(self) -> dict:
        if CONFLICTS_ID not in self.lists:
            self.lists[CONFLICTS_ID] = {"id": CONFLICTS_ID, "name": "⚠ Conflicts",
                                        "items": {}, "links": {}}
        return self.lists[CONFLICTS_ID]

    def set_hidden(self, lid: str, hidden: bool):
        if lid in self.lists and lid != CONFLICTS_ID:
            self.lists[lid]["hidden"] = hidden

    def visible_lists(self, hidden: bool | None = False):
        """hidden=False: only shown lists; True: only hidden ones; None: all."""
        return [l for l in self._all_lists() if hidden is None or bool(l.get("hidden")) == hidden]

    def delete_list(self, lid: str):
        """Tombstone the list and everything in it (items + strings), exactly like deleting each item. The log stays in git history."""
        lst = self.lists.get(lid)
        if not lst or lid == CONFLICTS_ID:
            return
        for it in [i for i in lst["items"].values() if not i.get("deleted")]:
            self.delete_item(lst, it)
        for lk in lst["links"].values():
            lk.setdefault("deleted", now())
        lst["deleted"] = now()
        self.order = [i for i in self.order if i != lid]

    def rename_list(self, lid: str, name: str):
        if lid in self.lists and lid != CONFLICTS_ID and name.strip():
            self.lists[lid]["name"] = name.strip()

    def _all_lists(self):
        ids = [i for i in self.order if i in self.lists and not self.lists[i].get("deleted")]
        ids += [i for i in sorted(self.lists) if i not in ids and i != CONFLICTS_ID and not self.lists[i].get("deleted")]
        c = self.lists.get(CONFLICTS_ID)
        if c and live_items(c):
            ids.append(CONFLICTS_ID)
        return [self.lists[i] for i in ids]

    def find_item(self, item_id: str):
        for lst in self.lists.values():
            it = lst["items"].get(item_id)
            if it and not it.get("deleted"):
                return lst, it
        return None, None

    # ---- items -------------------------------------------------------
    def add_item(self, list_id, text, parent=None) -> dict:
        lst = self.lists[list_id]
        sibs = children(lst, parent)
        pos = between(sibs[-1]["pos"] if sibs else None, None)
        it = new_item(text, parent, pos)
        lst["items"][it["id"]] = it
        return it

    def touch(self, it: dict, **fields):
        it.update(fields)
        it["updated"] = now()

    def delete_item(self, lst, it):
        stack = [it]
        while stack:
            cur = stack.pop()
            cur["deleted"] = now()
            stack.extend(children(lst, cur["id"]))
        dead = {i["id"] for i in lst["items"].values() if i.get("deleted")}
        for other in self.lists.values():             # strings may live in any list: drop every string touching a removed item
            for lk in other["links"].values():
                if lk["a"] in dead or lk["b"] in dead:
                    lk.setdefault("deleted", now())

    def move(self, lst, it, direction: str):
        """up/down among siblings; in = become child of previous sibling; out = become sibling of parent."""
        sibs = children(lst, it["parent"])
        idx = next(i for i, s in enumerate(sibs) if s["id"] == it["id"])
        if direction in ("up", "down"):
            j = idx - 1 if direction == "up" else idx + 1
            if not 0 <= j < len(sibs):
                return
            if direction == "up":
                lo = sibs[j - 1]["pos"] if j > 0 else None
                self.touch(it, pos=between(lo, sibs[j]["pos"]))
            else:
                hi = sibs[j + 1]["pos"] if j + 1 < len(sibs) else None
                self.touch(it, pos=between(sibs[j]["pos"], hi))
        elif direction == "in" and idx > 0:
            prev = sibs[idx - 1]
            kids = children(lst, prev["id"])
            self.touch(it, parent=prev["id"], pos=between(kids[-1]["pos"] if kids else None, None))
        elif direction == "out" and it["parent"] in lst["items"]:
            par = lst["items"][it["parent"]]
            uncles = children(lst, par["parent"])
            k = next(i for i, s in enumerate(uncles) if s["id"] == par["id"])
            after = uncles[k + 1]["pos"] if k + 1 < len(uncles) else None
            self.touch(it, parent=par["parent"], pos=between(par["pos"], after))

    # ---- sub-items are markdown lines ------------------------------------------------------------
    def locked(self, lst: dict, it: dict) -> bool:
        """A checked item that has checklist lines is frozen (text, lines). Its own checkbox stays live: unchecking unlocks it."""
        from . import mdparse
        return bool(it["done"]) and mdparse.has_boxes(it["text"])

    def sync_done_up(self, lst: dict, it: dict):
        """After a checklist line changed: the item is done exactly when ALL its lines are done (items without lines are left alone).
        Ticking an item itself never touches its lines."""
        from . import mdparse
        d, t = mdparse.progress(it["text"])
        if t and it["done"] != (d == t):
            self.touch(it, done=(d == t))

    def add_line(self, it: dict, text: str):
        from . import mdparse
        self.touch(it, text=mdparse.insert_block(it["text"], [f"* [ ] {text.strip()}"]))

    def flatten(self) -> bool:
        """MIGRATION: older data had nested child items. Sub-items are now markdown lines, so every child becomes a `* [ ]` row
        (with its whole body as continuation) at the end of its parent's text; strings on the child move to the parent."""
        from . import mdparse
        changed = False
        for lst in self.lists.values():
            items = lst["items"]

            def depth(i):
                d, cur, seen = 0, i, set()
                while cur["parent"] in items and cur["id"] not in seen:
                    seen.add(cur["id"]); cur = items[cur["parent"]]; d += 1
                return d
            kids = sorted((i for i in items.values() if i["parent"] is not None and not i.get("deleted")),
                          key=lambda i: (-depth(i), i["pos"], i["id"]))
            touched = {}
            for c in kids:
                par = items.get(c["parent"])
                changed = True
                if par is None or par.get("deleted"):
                    self.touch(c, parent=None)
                    continue
                block = mdparse.item_to_block(c["text"], c["done"]) or [f"* [{'x' if c['done'] else ' '}] (untitled)"]
                self.touch(par, text=mdparse.insert_block(par["text"], block))
                for other in self.lists.values():
                    for lk in other["links"].values():
                        if lk.get("deleted"):
                            continue
                        for end in ("a", "b"):
                            if lk[end] == c["id"]:
                                lk[end] = par["id"]
                        if lk["a"] == lk["b"]:
                            lk["deleted"] = now()
                c["deleted"] = now(); c["updated"] = now()
                touched[par["id"]] = par
            for par in touched.values():
                self.sync_done_up(lst, par)
        return changed

    def link_index(self):
        """-> (item_list: live item id -> list id, links: live string records). Strings are found by their END ITEMS, so they
        may connect items of different lists and survive moves between lists."""
        where = {i["id"]: lid for lid, l in self.lists.items() for i in l["items"].values() if not i.get("deleted")}
        links = [lk for l in self.lists.values() for lk in l["links"].values()
                 if not lk.get("deleted") and lk["a"] in where and lk["b"] in where]
        return where, links

    def _slot(self, dst: dict, parent, before, after, exclude=None) -> str:
        """Fractional position under `parent` in `dst`, before/after a sibling (else last). Respaces tied siblings."""
        sibs = [x for x in children(dst, parent) if x["id"] != exclude]

        def slot():
            at = len(sibs)
            for ref, off in ((before, 0), (after, 1)):
                if ref:
                    k = next((i for i, x in enumerate(sibs) if x["id"] == ref), None)
                    if k is not None:
                        at = k + off
            return (sibs[at - 1]["pos"] if at > 0 else None), (sibs[at]["pos"] if at < len(sibs) else None)

        lo, hi = slot()
        if lo is not None and hi is not None and lo >= hi:       # tied positions (concurrent appends): respace siblings
            prev = None
            for x in sibs:
                self.touch(x, pos=between(prev, None)); prev = x["pos"]
            lo, hi = slot()
        return between(lo, hi)

    def place_new(self, dst_id: str, text: str, done=False, parent=None, before=None, after=None) -> dict:
        dst = self.lists[dst_id]
        if parent is not None and (parent not in dst["items"] or dst["items"][parent].get("deleted")):
            parent = None
        it = new_item(text, parent, self._slot(dst, parent, before, after))
        it["done"] = bool(done)
        dst["items"][it["id"]] = it
        return it

    def drop(self, item_id, dst_id, parent=None, before=None, after=None) -> bool:
        """Drag & drop: put item (with its subtree) under `parent` in list `dst_id`, before/after a sibling (else last).
        Works within a list and ACROSS lists (records move; ids stay, so history/merge identity is kept)."""
        src, it = self.find_item(item_id)
        dst = self.lists.get(dst_id)
        if it is None or dst is None or before == item_id or after == item_id:
            return False
        sub, stack = [], [it]
        while stack:                                   # whole subtree, parents first
            cur = stack.pop(); sub.append(cur)
            stack.extend(children(src, cur["id"]))
        ids = {i["id"] for i in sub}
        if parent in ids:
            return False                               # cannot drop into itself or a descendant
        if parent is not None and (parent not in dst["items"] or dst["items"][parent].get("deleted")):
            parent = None
        pos = self._slot(dst, parent, before, after, exclude=item_id)
        if src is dst:
            self.touch(it, parent=parent, pos=pos)
            return True
        t = now()
        for i in sub:
            rec = dict(i); rec.pop("deleted", None); rec.pop("moved", None); rec["updated"] = t
            if i is it:
                rec["parent"], rec["pos"] = parent, pos
            dst["items"][i["id"]] = rec
            i["deleted"], i["updated"] = t, t
            i["moved"] = dst_id                                # tombstone remembers where it went (merge carries edits there)
        return True                                        # strings follow their items (they are resolved across lists)

    # ---- serialisation ----------------------------------------------
    def to_files(self, base_files: dict[str, str] | None = None) -> dict[str, str]:
        """Files to store. With base_files (what the remote held when we last
        synced) each changed list gets exactly one line APPENDED to its log."""
        from . import logfmt
        base_files = base_files or {}
        files = {"ghtodo.json": json.dumps({"v": SCHEMA, "order": self.order}, indent=1) + "\n"}
        t = now()
        for lid, lst in self.lists.items():
            path = f"lists/{lid}.log"
            old = base_files.get(path, "")
            files[path] = logfmt.append(old, logfmt.replay(old) if old else None, lst, t, lid)
        return files

    @classmethod
    def from_files(cls, files: dict[str, str]) -> "Workspace":
        from . import logfmt
        ws = cls()
        meta = json.loads(files.get("ghtodo.json", '{"order":[]}'))
        ws.order = meta.get("order", [])
        for path, text in files.items():
            if path.startswith("lists/") and path.endswith(".log"):
                lst = logfmt.replay(text)
                if lst:
                    lst["id"] = path[len("lists/"):-len(".log")]
                    lst.pop("_lines", None)
                    ws.lists[lst["id"]] = lst
        return ws


def children(lst: dict, parent: str | None, include_deleted=False) -> list[dict]:
    out = [i for i in lst["items"].values()
           if i["parent"] == parent and (include_deleted or not i.get("deleted"))]
    return sorted(out, key=lambda i: (i["pos"], i["id"]))


def child_index(lst: dict) -> dict:
    """parent id -> sorted live children, built in ONE pass (children() per node would be O(N^2))."""
    idx: dict = {}
    for i in lst["items"].values():
        if not i.get("deleted"):
            idx.setdefault(i["parent"], []).append(i)
    for v in idx.values():
        v.sort(key=lambda i: (i["pos"], i["id"]))
    return idx


def active_items(lst: dict) -> list[dict]:
    """Live and not hidden: what the board shows and counts."""
    return [i for i in lst["items"].values() if not i.get("deleted") and not i.get("hidden")]


def hidden_items(lst: dict) -> list[dict]:
    return sorted((i for i in lst["items"].values() if not i.get("deleted") and i.get("hidden")), key=lambda i: (i["pos"], i["id"]))


def live_items(lst: dict) -> list[dict]:
    return [i for i in lst["items"].values() if not i.get("deleted")]


def gc_tombstones(ws: Workspace, cutoff_ms: int | None = None):
    cutoff = (now() - TOMBSTONE_TTL_MS) if cutoff_ms is None else cutoff_ms
    for lst in ws.lists.values():
        for coll in (lst["items"], lst["links"]):
            for k in [k for k, v in coll.items() if v.get("deleted", 1 << 62) < cutoff]:
                del coll[k]
