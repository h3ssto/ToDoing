"""Append-only compressed log per list  (lists/<id>.log).

Each line = urlsafe-base64( zlib( json(entry) ) ), entry =
  {"id": <12 hex>, "prev": <id of previous line|None>, "ts": ms,
   "name": str|absent, "items": [changed full item records], "links": [changed link records],
   "snap": true (only on compaction lines)}

State = replay lines in order, later records replace earlier ones by id.
A sync appends at most ONE line per changed list, so git history of a list
file is pure appends. Merging never looks at lines, only at replayed states
(see merge.py), so a compacted/rewritten log on either side is harmless.
"""
from __future__ import annotations

import base64
import hashlib
import json
import zlib

COMPACT_AFTER = 200  # lines


def _enc(entry: dict) -> str:
    raw = json.dumps(entry, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(zlib.compress(raw, 9)).decode().rstrip("=")


def _dec(line: str) -> dict:
    pad = "=" * (-len(line) % 4)
    return json.loads(zlib.decompress(base64.urlsafe_b64decode(line + pad)))


def replay(text: str) -> dict | None:
    lst, n = None, 0
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        e = _dec(line)
        n += 1
        if lst is None or e.get("snap"):
            lst = {"id": None, "name": "", "items": {}, "links": {}}
        if "name" in e:
            lst["name"] = e["name"]
        if "hidden" in e:
            lst["hidden"] = bool(e["hidden"])
        if "deleted" in e:
            lst["deleted"] = e["deleted"] or None
        for it in e.get("items", []):
            lst["items"][it["id"]] = it
        for lk in e.get("links", []):
            lst["links"][lk["id"]] = lk
    if lst is not None:
        lst["_lines"] = n
    return lst


def last_id(text: str) -> str | None:
    lines = [l for l in text.split("\n") if l.strip()]
    return _dec(lines[-1])["id"] if lines else None


def delta(base: dict | None, cur: dict) -> dict | None:
    b_items = base["items"] if base else {}
    b_links = base["links"] if base else {}
    d = {"items": [i for k, i in sorted(cur["items"].items()) if b_items.get(k) != i],
         "links": [l for k, l in sorted(cur["links"].items()) if b_links.get(k) != l]}
    if base is None or base["name"] != cur["name"]:
        d["name"] = cur["name"]
    if bool(cur.get("hidden")) != bool((base or {}).get("hidden")):
        d["hidden"] = bool(cur.get("hidden"))
    if cur.get("deleted") != (base or {}).get("deleted"):
        d["deleted"] = cur.get("deleted") or 0
    return d if (d["items"] or d["links"] or "name" in d or "hidden" in d or "deleted" in d) else None


def append(text: str, base: dict | None, cur: dict, ts: int, list_id: str) -> str:
    """Return new file text = text + one line (or text unchanged if nothing differs).
    Compacts to a single snapshot line when the log grows long."""
    d = delta(base, cur)
    if d is None:
        return text
    prev = last_id(text)
    n = (base or {}).get("_lines", 0) + 1
    entry = dict(d, prev=prev, ts=ts)
    if n > COMPACT_AFTER:
        entry = {"snap": True, "name": cur["name"], "hidden": bool(cur.get("hidden")), "deleted": cur.get("deleted") or 0, "prev": prev, "ts": ts,
                 "items": sorted(cur["items"].values(), key=lambda i: i["id"]),
                 "links": sorted(cur["links"].values(), key=lambda l: l["id"])}
        text = ""
    entry["id"] = hashlib.sha1(json.dumps(entry, sort_keys=True).encode()).hexdigest()[:12]
    line = _enc(entry)
    return (text if not text or text.endswith("\n") else text + "\n") + line + "\n"
