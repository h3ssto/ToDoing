"""Example lists (first-run 'Load example lists'). Sub-items are markdown `* [ ]` lines."""
from .model import Workspace, new_id


def load(ws: Workspace) -> str:
    def add(lid, text, color="", done=False):
        it = ws.add_item(lid, text)
        it["color"], it["done"] = color, done
        return it["id"]

    def link(lid, a, b):
        k = new_id(); ws.lists[lid]["links"][k] = {"id": k, "a": a, "b": b}

    t = ws.add_list("Today")["id"]
    add(t, "Reply to Sam about the **Friday** meeting", "red")
    add(t, "Groceries\n* [x] milk\n* [ ] oat milk\n* [ ] coffee beans\n* [ ] something green\nBuy the cheap eggs, the expensive ones are not better.", "green")
    dentist = add(t, "Call the dentist", done=True)
    add(t, "Read: *Designing Data-Intensive Applications*, ch. 5\nBring notes to the book club.", "blue")

    h = ws.add_list("Home renovation")["id"]
    kitchen = add(h, "Kitchen\n* [ ] Choose tiles\n  Samples arrive Tuesday.\n  * [x] order samples\n  * [ ] decide on grout colour\n"
                     "* [ ] Book the plumber\n* [ ] Measure the counter\n  * [ ] width\n  * [ ] depth\n  * [ ] sink cut-out", "orange")
    bath = add(h, "Bathroom\n* [ ] Waterproofing\n  Must happen **before** tiling.\n* [ ] Order the mirror", "blue")
    plumber = add(h, "Call the plumber about the **leak** https://example.com/plumbers", "red")
    link(h, kitchen, bath); link(h, plumber, bath)
    link(t, dentist, plumber)

    p = ws.add_list("Trip to Lisbon")["id"]
    f = add(p, "Flights\n* [x] compare prices\n* [ ] book outbound\n* [ ] book return", "purple")
    s = add(p, "Stay\n* [ ] shortlist 3 places\n* [ ] ask about luggage storage", "purple")
    add(p, "Packing\n* [ ] passport\n* [ ] charger\n* [ ] sunscreen\n* [ ] light jacket")
    link(p, f, s)
    return t
