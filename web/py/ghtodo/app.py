"""HTMX-style request router: handle(method, path, params) -> HTML fragment.
Pure Python (no browser imports) so it runs under CPython tests too."""
from __future__ import annotations

import html
import json
import re

from markdown_it import MarkdownIt

from . import demo, mdparse
from .model import COLORS, Workspace, active_items, hidden_items, new_id, now

md = MarkdownIt("commonmark", {"html": False, "linkify": True}).enable("linkify")
md.linkify.set({"fuzzy_link": False, "fuzzy_email": False})      # only explicit http(s):// URLs become links


def _link_open(self, tokens, idx, options, env):
    tokens[idx].attrSet("target", "_blank")
    tokens[idx].attrSet("rel", "noopener noreferrer")
    return self.renderToken(tokens, idx, options, env)


md.add_render_rule("link_open", _link_open)
E = html.escape


def fmt_progress(done: int, total: int) -> str:
    """'3' style plain counter until something is checked, then '33% · 1/3'."""
    if not total:
        return ""
    return f"{round(100 * done / total)}% · {done}/{total}" if done else f"{done}/{total}"


def title(name: str) -> str:
    """List names follow the item rule: leading '#'s are markup, not part of the name."""
    return E(re.sub(r"^\s*#{1,6}\s+", "", name).strip() or name)


EMPTY = '<div class="empty-hint"></div>'


def ic(name: str) -> str:
    return f'<i class="fa-solid fa-{name}" aria-hidden="true"></i>'


PLUS = f'<button class="plus" aria-label="Add" title="Add">{ic("plus")}</button>'


class App:
    def __init__(self, ws: Workspace | None = None, persist=lambda ws: None, sync_status=lambda: ""):
        self.ws = ws or Workspace()
        self.persist = persist          # called after every mutation (-> IndexedDB)
        self.sync_status = sync_status
        self.dirty = False
        self.ws.flatten()                   # migrate old nested items into markdown sub-item lines
        self._where, self._draw, self._stubs = {}, [], {}
        self.show_hidden = False
        self.reveal: set[str] = set()      # lists whose hidden items are shown
        self.sel: list[str] | None = None   # None = all lists as columns; [id] = that list opened; [a,b,..] = chosen columns
        self.mode = "tree"                  # tree | color  (opened list only)

    # ---- routing -----------------------------------------------------
    def handle(self, method: str, path: str, p: dict) -> str:
        method = method.upper()
        for m, rx, fn in ROUTES:
            if m == method and (mo := re.fullmatch(rx, path)):
                out = fn(self, p, *mo.groups())
                if method != "GET":
                    self.dirty = True
                    self.persist(self.ws)
                return out
        return f'<p class="err">no route {E(method)} {E(path)}</p>'

    # ---- view state --------------------------------------------------
    def shown(self) -> list[dict]:
        lists = self.ws.visible_lists()
        if self.sel is not None:
            chosen = [l for l in self.ws.visible_lists(None) if l["id"] in self.sel]   # an opened list may be a hidden one
            if chosen:
                return chosen
            self.sel = None                              # stale selection (list vanished)
        return lists

    def is_detail(self) -> bool:
        return self.sel is not None and len(self.shown()) == 1

    # ---- views -------------------------------------------------------
    def shell(self) -> str:
        self._prepare_links()
        lists = self.ws.visible_lists()
        hid = self.ws.visible_lists(True)
        shown_ids = {l["id"] for l in self.shown()} if lists or hid else set()
        pick = lambda lid: self.sel is not None and lid in shown_ids
        side = (f'<li class="all {"on" if self.sel is None else ""}"><a href="#" hx-get="/view/all" hx-target="#app">{ic("table-columns")}<span>All lists</span></a></li>'
                + "".join(
                    f'<li data-droplist="{l["id"]}" data-name="{E(l["name"], quote=True)}" class="{"on" if pick(l["id"]) else ""}">'
                    f'<input type="checkbox" class="pick" {"checked" if pick(l["id"]) else ""} hx-post="/view/toggle/{l["id"]}" hx-target="#app" aria-label="Show side by side">'
                    f'<a href="#" hx-get="/view/open/{l["id"]}" hx-target="#app"><span>{title(l["name"])}</span></a>{self._count(l)}'
                    f'<span class="acts"><button class="ib ren" data-rename="{l["id"]}" aria-label="Rename list" title="Rename">{ic("pen")}</button>'
                    f'<button class="ib" hx-post="/list/{l["id"]}/hide" hx-target="#app" aria-label="Hide list" title="Hide">{ic("eye-slash")}</button></span></li>' for l in lists))
        if hid:
            side += (f'<li class="more"><a href="#" hx-post="/view/hidden" hx-target="#app">{ic("eye" if self.show_hidden else "eye-slash")}'
                     f'<span>{"Hide" if self.show_hidden else "Show"} hidden ({len(hid)})</span></a></li>')
            if self.show_hidden:
                side += "".join(
                    f'<li class="off {"on" if pick(l["id"]) else ""}" data-name="{E(l["name"], quote=True)}">'
                    f'<a href="#" hx-get="/view/open/{l["id"]}" hx-target="#app"><span>{title(l["name"])}</span></a>'
                    f'<span class="acts"><button class="ib ren" data-rename="{l["id"]}" aria-label="Rename list" title="Rename">{ic("pen")}</button>'
                    f'<button class="ib" hx-post="/list/{l["id"]}/unhide" hx-target="#app" aria-label="Restore list" title="Restore">{ic("rotate-left")}</button>'
                    f'<button class="ib del" data-confirm="Delete?" hx-post="/list/{l["id"]}/delete" hx-target="#app" aria-label="Delete list for good" title="Delete for good">{ic("trash")}</button></span></li>' for l in hid)
        main = self.main_html() if lists or hid or self.sel is not None else (
            '<div class="empty"><button hx-post="/demo" hx-target="#app">Load example lists</button></div>')
        return (f'<aside><ul>{side}</ul><form class="newlist" hx-post="/list" hx-target="#app">'
                f'<input name="name" placeholder="New list" required autocomplete="off"><button class="plus" aria-label="Create list" title="Create list">{ic("plus")}</button></form>'
                f'<div id="sync" hx-get="/sync/status" hx-trigger="load, every 5s">{self.sync_status()}</div></aside>'
                f'<main id="main">{main}</main>')

    def _prepare_links(self):
        """Once per render: which items carry strings, split into same-list (drawn as curves) and cross-list (drawn as stubs)."""
        where, links = self.ws.link_index()
        visible = {l["id"] for l in self.shown()}
        self._where, self._draw, self._stubs = where, [], {}
        for lk in links:
            la, lb = where[lk["a"]], where[lk["b"]]
            if self.ws.lists[la]["items"][lk["a"]].get("hidden") or self.ws.lists[lb]["items"][lk["b"]].get("hidden"):
                continue
            if la in visible and lb in visible:
                self._draw.append([lk["a"], lk["b"]])            # both lists on screen: draw the string itself
            else:
                for me, other in ((lk["a"], lk["b"]), (lk["b"], lk["a"])):
                    if where[me] in visible:                     # partner list hidden: dashed stub + its name
                        self._stubs.setdefault(me, []).append((where[other], other))

    def main_html(self) -> str:
        """Contents of #main for the current view. Every mutation returns this, so all visible columns refresh together."""
        shown = self.shown()
        if not shown:
            return ""
        self._prepare_links()
        if self.is_detail():
            return self.list_view(shown[0]["id"], self.mode)
        return f'<div class="cols" data-links="{self._links_attr()}">' + "".join(self.column_html(l) for l in shown) + "</div>"

    def _add_form(self, list_id, cls="add") -> str:
        return (f'<form class="{cls}" hx-post="/list/{list_id}/item" hx-target="#main">'
                f'<textarea name="text" rows="1" placeholder="Add item…" required></textarea>{PLUS}</form>')

    def _count(self, lst) -> str:
        live = active_items(lst)
        return f'<span class="prog">{fmt_progress(sum(i["done"] for i in live), len(live)) if live else ""}</span>'

    def _links_attr(self) -> str:
        return E(json.dumps(self._draw), quote=True)

    def stubs_html(self, item_id: str) -> str:
        """Cross-list strings: a short dashed line + the name of the list the other end lives in (click = open that list)."""
        out = []
        for lid, other in self._stubs.get(item_id, [])[:3]:
            lst = self.ws.lists[lid]
            oname = mdparse.split_name(lst["items"][other]["text"])[0]
            out.append(f'<a class="stub" href="#" hx-get="/view/open/{lid}" hx-target="#app" title="connected to “{E(oname, quote=True)}” in {E(lst["name"], quote=True)}">'
                       f'{title(lst["name"])}</a>')
        extra = len(self._stubs.get(item_id, [])) - 3
        return "".join(out) + (f'<span class="prog">+{extra}</span>' if extra > 0 else "")

    def stats(self, lst) -> tuple[str, str]:
        """(counter text, progress-bar html): plain item count until something is checked, then '33% · 1/3' + a thin bar."""
        live = active_items(lst)
        d, n = sum(i["done"] for i in live), len(live)
        counter = fmt_progress(d, n) if d else str(n)
        bar = f'<i class="bar" style="width:{round(100 * d / n)}%"></i>' if d and n else ""
        return counter, bar

    def column_html(self, lst) -> str:
        counter, bar = self.stats(lst)
        return (f'<section class="col" data-list="{lst["id"]}"><header><a href="#" hx-get="/view/open/{lst["id"]}" hx-target="#app">'
                f'{title(lst["name"])}</a><span class="prog">{counter}</span>{bar}</header>'
                f'<div class="board" data-list="{lst["id"]}">{self.items_html(lst) or EMPTY}</div>'
                f'{self._add_form(lst["id"])}{self.hidden_html(lst)}</section>')

    def list_view(self, list_id, mode="tree") -> str:
        lst = self.ws.lists[list_id]
        tabs = "".join(f'<a href="#" class="{"on" if mode == m else ""}" hx-get="/main?mode={m}" '
                       f'hx-target="#main">{lbl}</a>' for m, lbl in (("tree", "List"), ("color", "By color")))
        if mode == "color":
            body = ""
            for c in COLORS:
                its = [i for i in self.ordered(lst) if i["color"] == c]
                if its:
                    body += (f'<h3 class="grp c-{c or "none"}" data-color="{c}">{c or "no color"}</h3><ul class="items">'
                             + "".join(self.item_html(lst, i) for i in its) + "</ul>")
        else:
            body = self.items_html(lst) or EMPTY
        counter, bar = self.stats(lst)
        return (f'<div class="detail" data-links="{self._links_attr()}"><header class="pagehead"><h2 data-rename="{list_id}" data-name="{E(lst["name"], quote=True)}">{title(lst["name"])}</h2>'
                f'<span class="prog">{counter}</span><nav>{tabs}</nav>{bar}</header>'
                f'<div class="board" data-mode="{mode}" data-list="{list_id}">{body}</div>{self._add_form(list_id)}{self.hidden_html(lst)}</div>')

    @staticmethod
    def ordered(lst) -> list[dict]:
        """Items are a flat, ordered list: sub-items are markdown lines inside an item, never separate records."""
        return sorted(active_items(lst), key=lambda i: (i["pos"], i["id"]))

    def items_html(self, lst) -> str:
        its = self.ordered(lst)
        return '<ul class="items">' + "".join(self.item_html(lst, i) for i in its) + "</ul>" if its else ""

    def hidden_html(self, lst) -> str:
        """Per-list footer: 'Show hidden (n)' and, when revealed, the hidden items with restore / delete-for-good."""
        hid = hidden_items(lst)
        if not hid:
            return ""
        on = lst["id"] in self.reveal
        out = f'<a class="more" href="#" hx-post="/list/{lst["id"]}/reveal" hx-target="#main">{ic("eye" if on else "eye-slash")} {"Hide" if on else "Show"} hidden ({len(hid)})</a>'
        if on:
            out += '<ul class="items hidden">' + "".join(
                f'<li class="item hid c-{i["color"] or "none"}" data-id="{i["id"]}"><div class="row"><strong class="name">{md.renderInline(mdparse.split_name(i["text"])[0]) or "(empty)"}</strong>'
                f'<span class="hbtns"><button hx-post="/item/{i["id"]}/unhide" hx-target="#main" title="restore" aria-label="Restore">{ic("rotate-left")}</button>'
                f'<button hx-delete="/item/{i["id"]}" hx-target="#main" title="delete for good" aria-label="Delete for good">{ic("trash")}</button></span></div></li>' for i in hid) + "</ul>"
        return f'<div class="hiddenbox">{out}</div>'

    def tools_html(self, lst, it) -> str:
        """Per-item toolbar. Rendered lazily (first hover/focus) so a 1000-item list is ~10x smaller HTML."""
        iid = it["id"]
        colors = "".join(f'<button class="sw c-{c or "none"}" title="{c or "none"}" hx-post="/item/{iid}/color" '
                         f'hx-vals=\'{{"color":"{c}"}}\' hx-target="#main"></button>' for c in COLORS)
        add = "" if self.ws.locked(lst, it) else f'<button hx-get="/item/{iid}/addsub" hx-target="closest li" hx-swap="beforeend" title="add sub-item">{ic("plus")}</button>'
        return (f'{add}<button class="link" data-link="{iid}" title="connect">{ic("link")}</button>{colors}'
                f'<button hx-post="/item/{iid}/hide" hx-target="#main" title="hide" aria-label="Hide">{ic("eye-slash")}</button>')

    def body_html(self, text: str, item_id: str | None = None, locked: bool = False) -> str:
        """Rendered markdown body: prose + interactive sub-item rows (a row may carry continuation text)."""
        parts = []
        for kind, v in mdparse.segments(mdparse.split_name(text)[1]):
            if kind == "md":
                parts.append(f'<div class="md">{md.render(v)}</div>')
                continue
            rows = []
            for c in v:
                checked = "checked" if c["done"] else ""
                if item_id and not locked:
                    box = f'<input type="checkbox" {checked} hx-post="/item/{item_id}/check/{c["line"]}" hx-target="#main" hx-swap="innerHTML">'
                    drag = f' draggable="true" data-item="{item_id}" data-line="{c["line"]}"'
                else:
                    box, drag = f'<input type="checkbox" disabled {checked}>', ""
                cont = f'<div class="cont md">{md.render(c["cont"])}</div>' if c["cont"].strip() else ""
                rows.append(f'<li style="margin-left:{c["depth"] * 1.2}em" class="{"done" if c["done"] else ""}"{drag}>'
                            f'{box}<span>{md.renderInline(c["text"])}</span>{cont}</li>')
            parts.append(f'<ul class="check">{"".join(rows)}</ul>')
        return "".join(parts)

    def item_html(self, lst, it) -> str:
        name = mdparse.split_name(it["text"])[0]
        d, t = mdparse.progress(it["text"])
        prog = f'<span class="prog">{fmt_progress(d, t)}</span>' if t else ""
        locked = self.ws.locked(lst, it)                           # checked + has sub-items: its text and rows are frozen
        body = self.body_html(it["text"], it["id"], locked)
        conflict = ""
        if it.get("conflict"):
            cf = it["conflict"]
            keep = ""
            if cf["side"] != "info":
                keep = f'<button hx-post="/conflict/{it["id"]}/keep" hx-target="#app">keep this</button> '
            conflict = (f'<div class="conf">{E(cf["side"])} · {E(cf["field"])} {E(cf.get("note", ""))} {keep}'
                        f'<button hx-delete="/item/{it["id"]}" hx-target="#main">discard</button></div>')
        name_attrs = "" if locked else (f'hx-get="/item/{it["id"]}/edit" hx-trigger="click[!event.target.closest(\'a\')]" '
                                        'hx-target="closest li" hx-swap="outerHTML"')
        checked = "checked" if it["done"] else ""
        classes = f'item c-{it["color"] or "none"}' + (" done" if it["done"] else "") + (" locked" if locked else "")
        return (f'<li class="{classes}" id="i-{it["id"]}" data-id="{it["id"]}" draggable="true" '
                f'hx-get="/item/{it["id"]}/tools" hx-trigger="mouseenter once, focusin once" hx-target="find .tools" hx-swap="innerHTML">'
                f'<div class="row">'
                f'<input type="checkbox" {checked} hx-post="/item/{it["id"]}/toggle" hx-target="#main">'
                f'<strong class="name" {name_attrs}>{md.renderInline(name) or "(empty)"}</strong>{self.stubs_html(it["id"])}{prog}</div>'
                f'<div class="tools"></div>{body}{conflict}</li>')

    # ---- handlers ----------------------------------------------------
    def _ctx(self, item_id):
        return self.ws.find_item(item_id)


def r_shell(a, p): return a.shell()
def r_demo(a, p): demo.load(a.ws); a.sel = None; return a.shell()
def r_main(a, p):
    if p.get("mode") in ("tree", "color"): a.mode = p["mode"]
    return a.main_html()
def r_hide(a, p, lid):
    a.ws.set_hidden(lid, True)
    if a.sel is not None:
        a.sel = [i for i in a.sel if i != lid] or None
    return a.shell()
def r_delete_list(a, p, lid):
    l = a.ws.lists.get(lid)
    if l and l.get("hidden"):                                   # only a hidden list can be deleted: hide first, delete second
        a.ws.delete_list(lid)
        if a.sel is not None:
            a.sel = [i for i in a.sel if i != lid] or None
    return a.shell()
def r_rename_list(a, p, lid): a.ws.rename_list(lid, p.get("name", "")); return a.shell()
def r_unhide(a, p, lid): a.ws.set_hidden(lid, False); return a.shell()
def r_toggle_hidden(a, p): a.show_hidden = not a.show_hidden; return a.shell()
def r_view_all(a, p): a.sel = None; return a.shell()
def r_view_open(a, p, lid): a.sel = [lid]; return a.shell()
def r_view_toggle(a, p, lid):
    cur = [l["id"] for l in a.shown()] if a.sel is not None else []
    cur = [i for i in cur if i != lid] if lid in cur else cur + [lid]
    a.sel = cur or None
    return a.shell()
def r_new_list(a, p):
    l = a.ws.add_list(p["name"].strip() or "Untitled")
    if a.sel is not None: a.sel = [l["id"]]
    return a.shell()
def r_add(a, p, lid):
    a.ws.add_item(lid, p["text"]); return a.main_html()
def r_edit(a, p, iid):
    lst, it = a._ctx(iid)
    if a.ws.locked(lst, it):
        return a.item_html(lst, it)
    return (f'<li class="item editing"><form class="editor" hx-post="/item/{iid}" hx-target="#main">'
            f'<div class="hl-wrap"><pre class="hl" aria-hidden="true"></pre>'
            f'<textarea name="text" class="ed-body" rows="6" spellcheck="false" autofocus>{E(it["text"])}</textarea></div>'
            f'<div class="ed-actions"><button class="pri">{ic("check")} Save</button> <button type="button" data-cancel hx-get="/main" hx-target="#main">{ic("xmark")} Cancel</button></div></form></li>')
def r_addsub(a, p, iid):
    lst, it = a._ctx(iid)
    if a.ws.locked(lst, it): return ""
    return (f'<form class="add sub" hx-post="/item/{iid}/line" hx-target="#main">'
            f'<input name="text" placeholder="Sub-item…" autocomplete="off" autofocus required>{PLUS}</form>')
def r_line(a, p, iid):
    lst, it = a._ctx(iid)
    if p.get("text", "").strip() and not a.ws.locked(lst, it): a.ws.add_line(it, p["text"])
    return a.main_html()
def r_tools(a, p, iid):
    lst, it = a._ctx(iid); return a.tools_html(lst, it)
def r_save(a, p, iid):
    lst, it = a._ctx(iid)
    if p["text"].strip() and not a.ws.locked(lst, it):
        a.ws.touch(it, text=p["text"]); a.ws.sync_done_up(lst, it)
    return a.main_html()
def r_toggle(a, p, iid):
    lst, it = a._ctx(iid)
    a.ws.touch(it, done=not it["done"])                              # ticking an item never touches its sub-items
    return a.main_html()
def r_check(a, p, iid, line):
    lst, it = a._ctx(iid)
    if a.ws.locked(lst, it): return a.main_html()
    a.ws.touch(it, text=mdparse.toggle_check(it["text"], int(line)))
    a.ws.sync_done_up(lst, it); return a.main_html()
def r_color(a, p, iid):
    lst, it = a._ctx(iid); a.ws.touch(it, color=p.get("color", "")); return a.main_html()
def r_ihide(a, p, iid):
    lst, it = a._ctx(iid); a.ws.touch(it, hidden=True); return a.main_html()
def r_iunhide(a, p, iid):
    lst, it = a._ctx(iid); a.ws.touch(it, hidden=False); return a.main_html()
def r_reveal(a, p, lid):
    a.reveal ^= {lid}; return a.main_html()
def r_del(a, p, iid):
    lst, it = a._ctx(iid); a.ws.delete_item(lst, it); return a.main_html()


def _append_or_insert(text: str, block: list[str], zone, line) -> str:
    if line is None:
        return mdparse.insert_block(text, block)
    return mdparse.insert_block(text, block, **({"before_body_line": line} if zone == "before" else {"after_body_line": line}))


def _drop_line(a, p):
    """A sub-item line dragged out of an item: into another item's sub-items (onto a line, or onto an item = appended),
    or out as an item of its own (before/after another item, onto a list)."""
    sl, sit = a.ws.find_item(p["src_item"])
    ex = mdparse.extract_block(sit["text"], int(p["src_line"])) if sit else None
    if not ex:
        return
    rest, block = ex
    src_line, n = int(p["src_line"]), len(block)
    zone = p.get("zone", "into")
    tl = tit = None
    into_line = None                                              # -> into an item's sub-items
    if p.get("titem"):
        tl, tit = a.ws.find_item(p["titem"]); into_line = int(p["tline"])
    elif p.get("target") and zone == "into":
        tl, tit = a.ws.find_item(p["target"])
    if tit is not None:
        if tit is sit:                                            # indexes shift once our block is removed
            if into_line is not None:
                if src_line <= into_line < src_line + n:
                    return                                        # dropped onto itself
                into_line -= n if into_line >= src_line + n else 0
            new_text = _append_or_insert(rest, block, zone, into_line)
            a.ws.touch(sit, text=new_text)
        else:
            a.ws.touch(sit, text=rest)
            a.ws.touch(tit, text=_append_or_insert(tit["text"], block, zone, into_line))
            a.ws.sync_done_up(tl, tit)
    else:                                                         # -> out of the item: becomes an item of its own
        text, done = mdparse.block_to_item(block)
        if p.get("target"):
            tl, t = a.ws.find_item(p["target"])
            if t is None:
                return
            a.ws.place_new(tl["id"], text, done, before=t["id"] if zone == "before" else None, after=t["id"] if zone == "after" else None)
        elif p.get("list") in a.ws.lists:
            a.ws.place_new(p["list"], text, done)
        else:
            return
        a.ws.touch(sit, text=rest)
    a.ws.sync_done_up(sl, sit)


def _drop_item_into_item(a, p):
    """An item dropped onto another item (middle) or onto one of its lines becomes a sub-item line of it. Lossless: the item's
    whole body travels as the line's continuation."""
    sl, sit = a.ws.find_item(p["item"])
    tl, tit = a.ws.find_item(p.get("titem") or p["target"])
    if not sit or not tit or sit is tit:
        return
    block = mdparse.item_to_block(sit["text"], sit["done"])
    if not block:
        return
    line = int(p["tline"]) if p.get("titem") else None
    a.ws.touch(tit, text=_append_or_insert(tit["text"], block, p.get("zone", "into"), line))
    a.ws.delete_item(sl, sit)
    a.ws.sync_done_up(tl, tit)


def _drop_blocked(a, p) -> bool:
    """A checked item with sub-items is frozen: no line may leave it, nothing may be dropped into it."""
    if p.get("src_item"):
        sl, sit = a.ws.find_item(p["src_item"])
        if sit is not None and a.ws.locked(sl, sit):
            return True
    for key in ("titem", "target"):
        if p.get(key) and (key == "titem" or p.get("zone", "into") == "into"):
            tl, t = a.ws.find_item(p[key])
            if t is not None and a.ws.locked(tl, t):
                return True
    return False


def r_drop(a, p):
    """Drag & drop. Source: an item, or a sub-item line (src_item+src_line).
    Target: another item (target+zone before|after|into), a sub-item line (titem+tline+zone), or a list (list = append)."""
    if _drop_blocked(a, p):
        return a.main_html()
    if p.get("src_item"):
        _drop_line(a, p)
    elif p.get("titem") or (p.get("target") and p.get("zone", "into") == "into"):
        _drop_item_into_item(a, p)
    elif p.get("target"):
        tl, t = a.ws.find_item(p["target"])
        if t is not None:
            z = p["zone"]
            a.ws.drop(p["item"], tl["id"], parent=None, before=t["id"] if z == "before" else None, after=t["id"] if z == "after" else None)
    elif p.get("list") in a.ws.lists:
        a.ws.drop(p["item"], p["list"], None)
    return a.main_html()


def r_link(a, p):
    """Connect two items (any lists). Connecting an already-connected pair removes the string."""
    x, y = p["a"], p["b"]
    la, ia = a.ws.find_item(x); lb, ib = a.ws.find_item(y)
    if x != y and ia is not None and ib is not None:
        ex = [l for ls in a.ws.lists.values() for l in ls["links"].values()
              if not l.get("deleted") and {l["a"], l["b"]} == {x, y}]
        if ex:
            for l in ex: l["deleted"] = now()
        else:
            k = new_id(); la["links"][k] = {"id": k, "a": x, "b": y}
    return a.main_html()
def r_keep(a, p, iid):
    lst, it = a._ctx(iid); cf = it["conflict"]
    tl, target = a.ws.find_item(cf["item"])
    if target is not None and cf["field"] == "text":
        a.ws.touch(target, text=it["text"])
    for x in list(lst["items"].values()):                # drop the whole pair
        if x.get("conflict", {}).get("item") == cf["item"] and x.get("conflict", {}).get("field") == cf["field"]:
            x["deleted"] = now()
    return a.shell()
def r_status(a, p): return a.sync_status()


ROUTES = [
    ("GET", r"/", r_shell),
    ("GET", r"/main", r_main),
    ("GET", r"/view/all", r_view_all),
    ("GET", r"/view/open/(\w+)", r_view_open),
    ("POST", r"/view/toggle/(\w+)", r_view_toggle),
    ("POST", r"/move", r_drop),
    ("POST", r"/demo", r_demo),
    ("POST", r"/list", r_new_list),
    ("POST", r"/list/(\w+)/hide", r_hide),
    ("POST", r"/list/(\w+)/reveal", r_reveal),
    ("POST", r"/list/(\w+)/delete", r_delete_list),
    ("POST", r"/list/(\w+)/rename", r_rename_list),
    ("POST", r"/item/(\w+)/hide", r_ihide),
    ("POST", r"/item/(\w+)/unhide", r_iunhide),
    ("POST", r"/list/(\w+)/unhide", r_unhide),
    ("POST", r"/view/hidden", r_toggle_hidden),
    ("POST", r"/list/(\w+)/item", r_add),
    ("POST", r"/link", r_link),
    ("GET", r"/item/(\w+)/edit", r_edit),
    ("GET", r"/item/(\w+)/tools", r_tools),
    ("GET", r"/item/(\w+)/addsub", r_addsub),
    ("POST", r"/item/(\w+)", r_save),
    ("POST", r"/item/(\w+)/toggle", r_toggle),
    ("POST", r"/item/(\w+)/check/(\d+)", r_check),
    ("POST", r"/item/(\w+)/line", r_line),
    ("POST", r"/item/(\w+)/color", r_color),
    ("DELETE", r"/item/(\w+)", r_del),
    ("POST", r"/conflict/(\w+)/keep", r_keep),
    ("GET", r"/sync/status", r_status),
]
