import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "web" / "py"))
from ghtodo.model import Workspace, between
from ghtodo.mdparse import split_name, segments, toggle_check, progress
from ghtodo.merge import merge_workspaces


def test_between():
    a = None; keys = []
    for _ in range(50):
        k = between(a, None); keys.append(k); a = k
    assert keys == sorted(keys)
    assert "a" < between("a", "b") < "b" and "0" < between(None, "1") < "1"
    m = between("i", "j"); assert "i" < m < "j"


def test_markdown():
    t = "# Shop\nintro\n* [ ] milk\n  - [x] oat\nafter\n```\n* [ ] not\n```"
    name, body = split_name(t)
    assert name == "Shop"
    segs = segments(body)
    assert [k for k, _ in segs] == ["md", "check", "md"]
    assert segs[1][1][1]["depth"] == 1
    assert progress(t) == (1, 2)
    t2 = toggle_check(t, segs[1][1][0]["line"])
    assert progress(t2) == (2, 2)


def test_log_append_only_and_roundtrip():
    ws = Workspace(); l = ws.add_list("A"); ws.add_item(l["id"], "x")
    f1 = ws.to_files()
    ws2 = Workspace.from_files(f1)
    assert ws2.lists[l["id"]]["items"] == l["items"]
    it = next(iter(l["items"].values())); ws.touch(it, text="y")
    f2 = ws.to_files(f1)
    p = f"lists/{l['id']}.log"
    assert f2[p].startswith(f1[p]) and f2[p].count("\n") == 2
    assert ws.to_files(f2)[p] == f2[p]          # no change -> no new line


def clone(ws): return Workspace.from_files(ws.to_files())


def setup():
    ws = Workspace(); l = ws.add_list("A")
    i = ws.add_item(l["id"], "title\nline1\nline2\nline3")
    return ws, l["id"], i["id"]


def test_merge_clean_and_conflict():
    base, lid, iid = setup()
    ours, theirs = clone(base), clone(base)
    ours.lists[lid]["items"][iid]["text"] = "title\nLINE1\nline2\nline3"
    theirs.lists[lid]["items"][iid]["text"] = "title\nline1\nline2\nLINE3"
    m, n = merge_workspaces(base, ours, theirs)
    assert n == 0 and m.lists[lid]["items"][iid]["text"] == "title\nLINE1\nline2\nLINE3"
    ours.lists[lid]["items"][iid]["text"] = "title\nOURS\nline2\nline3"
    theirs.lists[lid]["items"][iid]["text"] = "title\nTHEIRS\nline2\nline3"
    m, n = merge_workspaces(base, ours, theirs)
    assert n == 1
    c = m.lists["_conflicts"]["items"].values()
    assert {i["conflict"]["side"] for i in c} == {"ours", "theirs"}
    assert "THEIRS" in m.lists[lid]["items"][iid]["text"]


def test_edit_beats_delete_and_adds():
    base, lid, iid = setup()
    ours, theirs = clone(base), clone(base)
    ours.delete_item(ours.lists[lid], ours.lists[lid]["items"][iid])
    theirs.lists[lid]["items"][iid]["done"] = True
    theirs.add_item(lid, "new")
    ours.add_item(lid, "mine")
    m, n = merge_workspaces(base, ours, theirs)
    assert not m.lists[lid]["items"][iid].get("deleted") and n == 1
    assert len([i for i in m.lists[lid]["items"].values() if i["text"] in ("new", "mine")]) == 2


# ---- regressions found by tests/fuzz.py ------------------------------------
def test_orphan_child_of_remotely_deleted_parent_is_hoisted():
    base, lid, iid = setup()
    ours, theirs = clone(base), clone(base)
    kid = ours.add_item(lid, "kid", iid)                       # child added here...
    theirs.delete_item(theirs.lists[lid], theirs.lists[lid]["items"][iid])   # ...parent deleted there
    m, _ = merge_workspaces(base, ours, theirs)
    assert m.lists[lid]["items"][kid["id"]]["parent"] is None and not m.lists[lid]["items"][kid["id"]].get("deleted")


def test_move_cycle_is_broken():
    base, lid, a = setup()
    b = base.add_item(lid, "b")["id"]
    ours, theirs = clone(base), clone(base)
    ours.lists[lid]["items"][a]["parent"] = b                  # a under b
    theirs.lists[lid]["items"][b]["parent"] = a                # b under a
    m, _ = merge_workspaces(base, ours, theirs)
    its = m.lists[lid]["items"]
    assert (its[a]["parent"], its[b]["parent"]).count(None) >= 1


def test_edit_vs_delete_keeps_both_texts():
    base, lid, iid = setup()
    ours, theirs = clone(base), clone(base)
    ours.lists[lid]["items"][iid]["text"] += "\nours-extra"
    it = theirs.lists[lid]["items"][iid]; it["text"] = "title\nTHEIRS\nline2\nline3"; theirs.delete_item(theirs.lists[lid], it)
    m, _ = merge_workspaces(base, ours, theirs)
    r = m.lists[lid]["items"][iid]
    assert not r.get("deleted") and "ours-extra" in r["text"] and "THEIRS" in r["text"]


def test_link_tombstone_choice_is_symmetric():
    base, lid, a = setup(); b = base.add_item(lid, "b")["id"]
    base.lists[lid]["links"]["k"] = {"id": "k", "a": a, "b": b}
    x, y = clone(base), clone(base)
    x.lists[lid]["links"]["k"]["deleted"] = 5; y.lists[lid]["links"]["k"]["deleted"] = 9
    assert merge_workspaces(base, x, y)[0].lists[lid]["links"] == merge_workspaces(base, y, x)[0].lists[lid]["links"]


# ---- drag & drop model --------------------------------------------------------
def _three():
    ws = Workspace(); a = ws.add_list("A")["id"]; b = ws.add_list("B")["id"]
    x, y, z = (ws.add_item(a, n)["id"] for n in "xyz")
    kid = ws.add_item(a, "kid", x)["id"]
    return ws, a, b, x, y, z, kid


def _order(ws, lid, parent=None):
    from ghtodo.model import children
    return [i["text"] for i in children(ws.lists[lid], parent)]


def test_drop_reorder_and_nest():
    ws, a, b, x, y, z, kid = _three()
    assert ws.drop(z, a, None, before=x) and _order(ws, a) == ["z", "x", "y"]
    assert ws.drop(z, a, None, after=y) and _order(ws, a) == ["x", "y", "z"]
    assert ws.drop(y, a, x) and _order(ws, a, x) == ["kid", "y"]          # into x (append)
    assert not ws.drop(x, a, kid)                                          # cannot nest into own descendant
    assert not ws.drop(x, a, x)


def test_drop_across_lists_moves_subtree():
    ws, a, b, x, y, z, kid = _three()
    lk = "k1"; ws.lists[a]["links"][lk] = {"id": lk, "a": x, "b": y}
    ws.add_item(b, "existing")
    assert ws.drop(x, b, None, before=next(iter(ws.lists[b]["items"])))
    assert _order(ws, b) == ["x", "existing"] and _order(ws, b, x) == ["kid"]
    assert _order(ws, a) == ["y", "z"]
    assert not ws.lists[a]["links"][lk].get("deleted")                     # strings follow their items...
    assert len(ws.link_index()[1]) == 1 and ws.link_index()[0][x] == b     # ...and now connect two different lists
    lst, it = ws.find_item(x); assert lst["id"] == b                       # unique live location
    assert ws.drop(x, a, None) and ws.find_item(x)[0]["id"] == a           # and back again


def test_drop_with_tied_positions():
    ws = Workspace(); a = ws.add_list("A")["id"]
    ids = [ws.add_item(a, n)["id"] for n in "pqr"]
    for i in ws.lists[a]["items"].values(): i["pos"] = "i"                 # concurrent appends tie
    assert ws.drop(ids[2], a, None, before=ids[0])
    order = _order(ws, a)
    assert order.index("r") == order.index("p") - 1 and sorted(order) == ["p", "q", "r"]   # r sits right before p


# ---- checkbox semantics --------------------------------------------------------------
def test_done_follows_sub_items_only_upwards():
    from ghtodo.app import App
    a = App(); a.handle("POST", "/list", {"name": "L"}); lid = a.ws.order[0]; it = a.ws.lists[lid]["items"]
    i = a.ws.add_item(lid, "P\n* [ ] a\n* [ ] b")["id"]
    a.handle("POST", f"/item/{i}/toggle", {})                                    # ticking the item leaves its sub-items alone
    assert it[i]["done"] and "[ ] a" in it[i]["text"] and "[ ] b" in it[i]["text"]
    a.handle("POST", f"/item/{i}/toggle", {})
    a.handle("POST", f"/item/{i}/check/0", {}); assert not it[i]["done"]
    a.handle("POST", f"/item/{i}/check/1", {}); assert it[i]["done"]             # last sub-item ticked -> item done
    a.handle("POST", f"/item/{i}/toggle", {})                                    # unlock again ...
    a.handle("POST", f"/item/{i}/check/0", {}); assert not it[i]["done"]         # ... reopening a sub-item reopens the item


def test_markdown_checkboxes_complete_parent():
    from ghtodo.app import App
    a = App(); a.handle("POST", "/list", {"name": "L"}); lid = a.ws.order[0]
    a.handle("POST", f"/list/{lid}/item", {"text": "Shop\n* [ ] milk\n* [ ] eggs"})
    iid = next(iter(a.ws.lists[lid]["items"]))
    a.handle("POST", f"/item/{iid}/check/0", {}); assert not a.ws.lists[lid]["items"][iid]["done"]
    a.handle("POST", f"/item/{iid}/check/1", {}); assert a.ws.lists[lid]["items"][iid]["done"]
    a.handle("POST", f"/item/{iid}/toggle", {});  assert "[x] milk" in a.ws.lists[lid]["items"][iid]["text"]   # parent click leaves boxes


# ---- a checked parent freezes its box ----------------------------------------------------------
def test_checked_item_with_sub_items_is_frozen():
    from ghtodo.app import App
    a = App(); a.handle("POST", "/list", {"name": "L"}); lid = a.ws.order[0]; it = a.ws.lists[lid]["items"]
    par = a.ws.add_item(lid, "Parent\n* [ ] one\n* [ ] two")["id"]; other = a.ws.add_item(lid, "other\n* [ ] o1")["id"]
    a.handle("POST", f"/item/{par}/toggle", {})                                   # check the item -> frozen, sub-items untouched
    assert it[par]["done"] and "[ ] one" in it[par]["text"]
    html = a.handle("GET", "/main", {}); assert html.count("disabled") == 2 and "locked" in html
    a.handle("POST", f"/item/{par}/check/0", {});             assert "[ ] one" in it[par]["text"]                   # cannot tick a sub-item
    a.handle("POST", f"/item/{par}", {"text": "X"});           assert it[par]["text"].startswith("Parent")           # cannot edit
    a.handle("POST", f"/item/{par}/line", {"text": "three"});  assert "three" not in it[par]["text"]                 # cannot add sub-items
    a.handle("POST", "/move", {"src_item": par, "src_line": "0", "target": other, "zone": "into"})                  # cannot drag lines out
    assert "[ ] one" in it[par]["text"] and "one" not in it[other]["text"]
    a.handle("POST", "/move", {"item": other, "target": par, "zone": "into"}); assert not it[other].get("deleted")  # nor drop into it
    a.handle("POST", "/move", {"item": other, "titem": par, "tline": "0", "zone": "after"}); assert not it[other].get("deleted")
    a.handle("POST", f"/item/{par}/toggle", {})                                   # uncheck -> unlocked
    a.handle("POST", f"/item/{par}/line", {"text": "three"}); assert it[par]["text"].endswith("* [ ] three")
    a.handle("POST", f"/item/{par}/check/0", {}); a.handle("POST", f"/item/{par}/check/1", {}); a.handle("POST", f"/item/{par}/check/2", {})
    assert it[par]["done"]                                                         # all sub-items ticked -> done (and frozen again)
    a.handle("DELETE", f"/item/{par}", {});                    assert it[par].get("deleted")                         # the frozen item can still be deleted


# ---- checklist drag & drop: text surgery + handlers ------------------------------------------
def _app_with(text, text2=None):
    from ghtodo.app import App
    a = App(); a.handle("POST", "/list", {"name": "L"}); lid = a.ws.order[0]
    ids = [a.ws.add_item(lid, text)["id"]]
    if text2 is not None: ids.append(a.ws.add_item(lid, text2)["id"])
    return a, lid, ids


def test_block_surgery_carries_nested_lines():
    from ghtodo import mdparse as m
    t = "T\n* [ ] a\n  more about a\n  * [x] a1\n* [ ] b"
    rest, block = m.extract_block(t, 0)
    assert rest == "T\n* [ ] b" and block == ["* [ ] a", "  more about a", "  * [x] a1"]
    assert m.insert_block(rest, block, before_body_line=0) == t
    assert m.insert_block(rest, block, after_body_line=0) == "T\n* [ ] b\n* [ ] a\n  more about a\n  * [x] a1"
    assert m.block_to_item(block) == ("a\nmore about a\n* [x] a1", False)
    assert m.item_to_block("Title\n* [ ] x", True) == ["* [x] Title", "  * [ ] x"]
    assert m.item_to_block("Title\nsome prose", False) == ["* [ ] Title", "  some prose"]     # lossless: prose becomes continuation
    seg = m.segments("* [ ] a\n  note\n  * [x] a1\n* [ ] b")[0][1]
    assert [r["text"] for r in seg] == ["a", "a1", "b"] and seg[0]["cont"] == "note" and seg[1]["depth"] == 1


def test_checklist_line_dragged_out_becomes_item():
    a, lid, (i1,) = _app_with("Shop\n* [ ] milk\n* [x] eggs")
    a.handle("POST", "/move", {"src_item": i1, "src_line": "1", "target": i1, "zone": "after"})   # beside its own item = a new item
    items = a.ws.lists[lid]["items"]
    assert items[i1]["text"] == "Shop\n* [ ] milk" and sorted(i["text"] for i in items.values()) == ["Shop\n* [ ] milk", "eggs"]
    eggs = next(i for i in items.values() if i["text"] == "eggs"); assert eggs["done"] and eggs["parent"] is None
    a.handle("POST", "/move", {"src_item": i1, "src_line": "0", "target": eggs["id"], "zone": "into"})   # onto another item = its sub-item
    assert items[eggs["id"]]["text"] == "eggs\n* [ ] milk" and items[i1]["text"] == "Shop"


def test_checklist_line_between_and_within_items():
    a, lid, (i1, i2) = _app_with("A\n* [ ] a1\n* [ ] a2\n* [ ] a3", "B\n* [ ] b1")
    it = a.ws.lists[lid]["items"]
    a.handle("POST", "/move", {"src_item": i1, "src_line": "0", "titem": i1, "tline": "2", "zone": "after"})   # reorder within
    assert it[i1]["text"] == "A\n* [ ] a2\n* [ ] a3\n* [ ] a1"
    a.handle("POST", "/move", {"src_item": i1, "src_line": "2", "titem": i1, "tline": "0", "zone": "before"})   # and back up
    assert it[i1]["text"] == "A\n* [ ] a1\n* [ ] a2\n* [ ] a3"
    a.handle("POST", "/move", {"src_item": i1, "src_line": "1", "titem": i2, "tline": "0", "zone": "before"})   # into another item
    assert it[i1]["text"] == "A\n* [ ] a1\n* [ ] a3" and it[i2]["text"] == "B\n* [ ] a2\n* [ ] b1"
    a.handle("POST", "/move", {"src_item": i1, "src_line": "0", "titem": i1, "tline": "0", "zone": "after"})   # onto itself: no-op
    assert it[i1]["text"] == "A\n* [ ] a1\n* [ ] a3"


def test_moving_last_open_line_out_completes_parent():
    a, lid, (i1, i2) = _app_with("A\n* [x] done\n* [ ] open", "B\n* [ ] b")
    a.handle("POST", "/move", {"src_item": i1, "src_line": "1", "titem": i2, "tline": "0", "zone": "after"})
    assert a.ws.lists[lid]["items"][i1]["done"] and not a.ws.lists[lid]["items"][i2]["done"]


def test_item_dragged_into_checklist():
    a, lid, (i1, i2) = _app_with("Target\n* [ ] t1", "Task\n* [ ] sub")
    a.ws.lists[lid]["items"][i2]["done"] = True
    a.handle("POST", "/move", {"item": i2, "titem": i1, "tline": "0", "zone": "after"})
    it = a.ws.lists[lid]["items"]
    assert it[i1]["text"] == "Target\n* [ ] t1\n* [x] Task\n  * [ ] sub" and it[i2].get("deleted")
    a2, l2, (j1, j2) = _app_with("T\n* [ ] x", "Has prose\nnot a checklist")             # prose is kept as the row's continuation
    a2.handle("POST", "/move", {"item": j2, "titem": j1, "tline": "0", "zone": "before"})
    assert a2.ws.lists[l2]["items"][j1]["text"] == "T\n* [ ] Has prose\n  not a checklist\n* [ ] x"


def test_dropping_an_item_into_a_parent_updates_the_parents_markdown():
    """The reported bug: 'into' used to create a separate nested record and leave the parent's markdown untouched."""
    a, lid, (par, kid) = _app_with("Parent\nintro\n* [ ] existing", "Kid\nsome body")
    it = a.ws.lists[lid]["items"]
    a.handle("POST", "/move", {"item": kid, "target": par, "zone": "into"})
    assert it[par]["text"] == "Parent\nintro\n* [ ] existing\n* [ ] Kid\n  some body"      # parent's markdown is the single truth
    assert it[kid].get("deleted") and all(i["parent"] is None for i in it.values())              # no nested records anywhere
    html = a.handle("GET", "/main", {})
    assert html.count('<li class="item') == 1 and "Kid" in html and "some body" in html          # and it renders as a sub-item row


def test_old_nested_items_are_migrated_to_markdown():
    ws = Workspace(); lid = ws.add_list("L")["id"]
    p = ws.add_item(lid, "Kitchen")["id"]
    c = ws.add_item(lid, "Tiles\nnote\n* [x] order", p)["id"]; g = ws.add_item(lid, "Grout", c)["id"]
    ws.lists[lid]["items"][g]["done"] = True
    assert ws.flatten() and not ws.flatten()                                                    # converts, then idempotent
    it = ws.lists[lid]["items"]
    assert it[p]["text"] == "Kitchen\n* [ ] Tiles\n  note\n  * [x] order\n  * [x] Grout"
    assert it[c].get("deleted") and it[g].get("deleted") and not it[p]["done"]


# ---- strings across lists ------------------------------------------------------------------------
def test_cross_list_strings():
    from ghtodo.app import App
    a = App(); a.handle("POST", "/list", {"name": "Alpha"}); a.handle("POST", "/list", {"name": "Beta"})
    la, lb = a.ws.order
    x = a.ws.add_item(la, "x")["id"]; y = a.ws.add_item(lb, "y")["id"]
    a.handle("POST", "/link", {"a": x, "b": y})
    both = a.handle("GET", "/main", {})                                                      # both lists visible: DRAWN, no stubs
    assert 'class="stub"' not in both and x in both and f'[[&quot;{x}&quot;, &quot;{y}&quot;]]' in both
    a.handle("GET", f"/view/open/{la}", {})                                                  # partner hidden: stub with its name
    one = a.handle("GET", "/main", {})
    assert one.count('class="stub"') == 1 and ">Beta</a>" in one and 'data-links="[]"' in one
    a.handle("POST", "/link", {"a": y, "b": x}); assert 'class="stub"' not in a.handle("GET", "/main", {})   # toggles off
    a.handle("POST", "/link", {"a": x, "b": y})
    a.ws.drop(y, la, None)                                                                   # moving keeps the string, now same-list
    assert 'class="stub"' not in a.handle("GET", "/main", {}) and a.ws.link_index()[1]
    a.ws.drop(y, lb, None); a.ws.delete_item(a.ws.lists[lb], a.ws.lists[lb]["items"][y])    # deleting an end kills it
    assert not a.ws.link_index()[1]
    from ghtodo.merge import repair
    a.handle("POST", "/link", {"a": x, "b": a.ws.add_item(lb, "z")["id"]}); repair(a.ws)     # repair keeps valid cross-list strings
    assert a.ws.link_index()[1]


def test_hide_list_roundtrip_and_merge():
    from ghtodo.merge import merge_workspaces
    from ghtodo.model import Workspace
    ws = Workspace(); a = ws.add_list("A"); b = ws.add_list("B"); ws.add_item(a["id"], "x")
    base = Workspace.from_files(ws.to_files())
    ws.set_hidden(a["id"], True)
    files = ws.to_files(base.to_files())
    back = Workspace.from_files(files)
    assert back.lists[a["id"]]["hidden"] and not back.lists[b["id"]].get("hidden")
    assert [l["id"] for l in back.visible_lists()] == [b["id"]] and [l["id"] for l in back.visible_lists(True)] == [a["id"]]
    other = Workspace.from_files(base.to_files())                       # remote edited an item, we hid the list
    other.add_item(a["id"], "y")
    m, _ = merge_workspaces(base, back, other)
    assert m.lists[a["id"]]["hidden"] and len([i for i in m.lists[a["id"]]["items"].values()]) == 2
    back.set_hidden(a["id"], False)
    assert not Workspace.from_files(back.to_files(files)).lists[a["id"]]["hidden"]


def test_hide_item_merge_and_counts():
    from ghtodo.merge import merge_workspaces
    from ghtodo.model import Workspace, active_items
    ws = Workspace(); l = ws.add_list("A"); lid = l["id"]
    it = ws.add_item(lid, "one"); ws.add_item(lid, "two")
    base = Workspace.from_files(ws.to_files())
    ours = Workspace.from_files(base.to_files()); theirs = Workspace.from_files(base.to_files())
    ours.touch(ours.lists[lid]["items"][it["id"]], hidden=True)
    theirs.touch(theirs.lists[lid]["items"][it["id"]], text="one edited")
    m, n = merge_workspaces(base, ours, theirs)
    got = m.lists[lid]["items"][it["id"]]
    assert got["hidden"] and got["text"] == "one edited" and n == 0
    assert len(active_items(m.lists[lid])) == 1
    back = Workspace.from_files(m.to_files())
    assert back.lists[lid]["items"][it["id"]]["hidden"]


def test_delete_list_roundtrip_merge_and_rename():
    from ghtodo.merge import merge_workspaces
    from ghtodo.model import Workspace, live_items
    ws = Workspace(); a = ws.add_list("A")["id"]; b = ws.add_list("B")["id"]
    x = ws.add_item(a, "x"); y = ws.add_item(b, "y"); ws.link(x["id"], y["id"]) if hasattr(ws, "link") else None
    base = Workspace.from_files(ws.to_files())
    # plain delete: survives a round trip, disappears from every view, strings die with it
    ours = Workspace.from_files(base.to_files()); ours.set_hidden(a, True); ours.delete_list(a)
    back = Workspace.from_files(ours.to_files(base.to_files()))
    assert back.lists[a]["deleted"] and [l["id"] for l in back.visible_lists(None)] == [b] and not live_items(back.lists[a])
    # delete on one device vs untouched on the other -> deleted
    theirs = Workspace.from_files(base.to_files())
    m, n = merge_workspaces(base, back, theirs)
    assert m.lists[a].get("deleted") and n == 0 and [l["id"] for l in m.visible_lists(None)] == [b]
    # delete vs edit on the other device -> the edit wins, list is back, note in Conflicts
    theirs.touch(theirs.lists[a]["items"][x["id"]], text="x edited")
    m, n = merge_workspaces(base, back, theirs)
    assert not m.lists[a].get("deleted") and a in [l["id"] for l in m.visible_lists(None)]
    assert any(i["text"] == "x edited" for i in live_items(m.lists[a])) and n >= 1
    # delete vs a NEW item on the other device -> list comes back with the new item
    theirs2 = Workspace.from_files(base.to_files()); theirs2.add_item(a, "fresh")
    m, _ = merge_workspaces(base, back, theirs2)
    assert [i["text"] for i in live_items(m.lists[a])] == ["fresh"]
    # rename merges one-sided
    r = Workspace.from_files(base.to_files()); r.rename_list(b, "  Bee ")
    m, _ = merge_workspaces(base, r, Workspace.from_files(base.to_files()))
    assert m.lists[b]["name"] == "Bee"


def test_only_hidden_lists_can_be_deleted():
    from ghtodo.app import App
    a = App(); a.handle("POST", "/list", {"name": "L"}); lid = a.ws.order[0]
    a.handle("POST", f"/list/{lid}/delete", {}); assert not a.ws.lists[lid].get("deleted")
    a.handle("POST", f"/list/{lid}/hide", {}); a.handle("POST", f"/list/{lid}/delete", {}); assert a.ws.lists[lid]["deleted"]
    assert "Show hidden" not in a.shell()


def test_share_key_roundtrip():
    from ghtodo import share
    tok = "github_pat_11ABC_xyz/+=?"
    key = share.encode(tok)
    assert key.startswith("todoing1.") and "=" not in key and tok not in key
    assert share.decode(key) == tok
    assert share.decode("https://me.github.io/app/#join=" + key) == tok         # a pasted link works too
    assert share.decode("  github_pat_plain  ") == "github_pat_plain"           # a bare token passes through
    for bad in ("todoing1.", "todoing1.@@@", "todoing1." + share.encode("")[9:]):
        try:
            share.decode(bad)
        except ValueError:
            continue
        raise AssertionError(bad)
