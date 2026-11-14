"""Item markdown: first line = name; `* [ ]` lines are the item's SUB-ITEMS (there is no other kind of nesting).

A checklist line may carry an indented continuation (prose, nested `* [ ]` lines). Text after a checklist run continues
*after* the sublist when rendered:

    Buy things              <- name
    intro text              <- md segment
    * [ ] milk              <- check run: rows ...
      needs to be oat       <-   ... with a continuation
      * [x] 1 litre         <-   ... and nested rows
    * [x] eggs
    and then some more      <- md segment (continues after the sublist)
"""
from __future__ import annotations

import re
import textwrap

CHECK = re.compile(r"^(\s*)[-*+]\s+\[([ xX])\]\s?(.*)$")
FENCE = re.compile(r"^\s*(```|~~~)")


def _indent(line: str) -> int:
    s = line.replace("\t", "    ")
    return len(s) - len(s.lstrip(" "))


def split_name(text: str) -> tuple[str, str]:
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        if ln.strip():
            name = re.sub(r"^\s*#{1,6}\s+", "", ln).strip()
            return name, "\n".join(lines[i + 1:])
    return "", ""


def _continuation_end(lines: list[str], i: int, base: int) -> int:
    """Exclusive end of the non-checklist lines indented under the row at i (blank gaps allowed if indented text follows)."""
    j = i + 1
    while j < len(lines):
        ln = lines[j]
        if CHECK.match(ln):
            break
        if ln.strip() and _indent(ln) > base:
            j += 1
            continue
        if not ln.strip():
            k = j + 1
            while k < len(lines) and not lines[k].strip():
                k += 1
            if k < len(lines) and not CHECK.match(lines[k]) and _indent(lines[k]) > base:
                j = k
                continue
        break
    return j


def segments(body: str) -> list[tuple[str, object]]:
    """-> [("md", str) | ("check", [ {line, depth, done, text, cont} ])]; `line` indexes body lines, `cont` = continuation markdown."""
    lines = body.split("\n")
    out: list[tuple[str, object]] = []
    md: list[str] = []
    run: list[dict] = []
    in_fence = False

    def flush_md():
        if md and "\n".join(md).strip():
            out.append(("md", "\n".join(md)))
        md.clear()

    def flush_run():
        if run:
            out.append(("check", list(run)))
        run.clear()

    i = 0
    while i < len(lines):
        ln = lines[i]
        if FENCE.match(ln):
            in_fence = not in_fence
        m = None if in_fence else CHECK.match(ln)
        if m:
            flush_md()
            base = _indent(ln)
            end = _continuation_end(lines, i, base)
            cont = textwrap.dedent("\n".join(lines[i + 1:end])).strip("\n")
            run.append({"line": i, "depth": base // 2, "done": m.group(2) in "xX", "text": m.group(3), "cont": cont})
            i = end
            continue
        flush_run()
        md.append(ln)
        i += 1
    flush_md()
    flush_run()
    return out


def toggle_check(text: str, body_line: int) -> str:
    """Flip checkbox on body line `body_line` (relative to text after the name line)."""
    lines = text.split("\n")
    first = next((i for i, l in enumerate(lines) if l.strip()), len(lines))
    k = first + 1 + body_line
    m = CHECK.match(lines[k]) if k < len(lines) else None
    if m:
        mark = " " if m.group(2) in "xX" else "x"
        lines[k] = re.sub(r"\[[ xX]\]", f"[{mark}]", lines[k], count=1)
    return "\n".join(lines)


def progress(text: str) -> tuple[int, int]:
    _, body = split_name(text)
    boxes = [c for kind, v in segments(body) if kind == "check" for c in v]
    return sum(c["done"] for c in boxes), len(boxes)


def has_boxes(text: str) -> bool:
    return progress(text)[1] > 0


def all_done(text: str) -> bool:
    d, t = progress(text)
    return t > 0 and d == t


# ---- moving checklist lines between items (drag & drop) ------------------------------------
def _locate(text: str, body_line: int):
    lines = text.split("\n")
    first = next((i for i, l in enumerate(lines) if l.strip()), len(lines))
    return lines, first + 1 + body_line


def _block_end(lines: list[str], k: int) -> int:
    """Exclusive end of the checklist row at k together with everything that belongs to it (continuation, nested rows)."""
    base = _indent(lines[k])
    e = k + 1
    while e < len(lines):
        ln = lines[e]
        if CHECK.match(ln):
            if _indent(ln) > base:
                e += 1
                continue
            break
        if ln.strip() and _indent(ln) > base:
            e += 1
            continue
        if not ln.strip():
            j = e + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines) and _indent(lines[j]) > base:
                e = j
                continue
        break
    return e


def extract_block(text: str, body_line: int):
    """Remove checklist row `body_line` (with its continuation and nested rows). -> (new_text, block_lines) or None."""
    lines, k = _locate(text, body_line)
    if k >= len(lines) or not CHECK.match(lines[k]):
        return None
    e = _block_end(lines, k)
    return "\n".join(lines[:k] + lines[e:]), lines[k:e]


def insert_block(text: str, block: list[str], before_body_line=None, after_body_line=None) -> str:
    """Insert rows before/after another checklist row (taking its indent) or, with neither, at the end of the text."""
    lines = text.split("\n")
    if before_body_line is None and after_body_line is None:
        lines = text.rstrip("\n").split("\n")
        at, ind = len(lines), 0
    else:
        k = _locate(text, before_body_line if before_body_line is not None else after_body_line)[1]
        if k >= len(lines) or not CHECK.match(lines[k]):
            return text
        at = k if before_body_line is not None else _block_end(lines, k)
        ind = _indent(lines[k])
    base = _indent(block[0])
    lines[at:at] = [" " * (ind + max(_indent(l) - base, 0)) + l.lstrip() if l.strip() else "" for l in block]
    return "\n".join(lines)


def block_to_item(block: list[str]) -> tuple[str, bool]:
    """A row becomes a new item: row text = title, everything under it (continuation, nested rows) = its body. -> (text, done)"""
    m = CHECK.match(block[0])
    rest = block[1:]
    while rest and not rest[-1].strip():
        rest.pop()
    body = textwrap.dedent("\n".join(l.replace("\t", "    ") for l in rest))
    return m.group(3) + (("\n" + body) if body.strip() else ""), m.group(2) in "xX"


def item_to_block(text: str, done: bool):
    """An item becomes a row: title = row text, its whole body = continuation. Lossless. -> lines | None (no title)"""
    name, body = split_name(text)
    if not name:
        return None
    rest = body.split("\n")
    while rest and not rest[-1].strip():
        rest.pop()
    return [f"* [{'x' if done else ' '}] {name}"] + [("  " + l) if l.strip() else "" for l in rest]
