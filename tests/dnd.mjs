// Drag & drop + board views in headless Chromium. Needs scripts/serve.py running on :8000.
import { chromium } from "playwright-core";
const b = await chromium.launch({ executablePath: process.env.CHROMIUM || "/usr/bin/chromium", args: ["--no-sandbox"] });
const p = await (await b.newContext({ viewport: { width: 1500, height: 900 } })).newPage();
const errs = []; p.on("pageerror", e => errs.push(e.message));
let fails = 0; const ok = (c, m) => { console.log(c ? "ok  " : "FAIL", m); if (!c) fails++; };
const col = (i) => p.locator(`.col >> nth=${i}`);
const names = async (i) => (await col(i).locator(".board > ul.items > li.item > .row .name").allTextContents()).map(s => s.trim());
const rows = async (i, item) => (await col(i).locator("li.item", { hasText: item }).first().locator("ul.check li > span").allTextContents()).map(s => s.trim());
const settle = () => p.waitForTimeout(350);
await p.goto("http://localhost:8000/?demo"); await p.waitForSelector(".col");
ok(await p.locator(".col").count() === 3, "default view = 3 lists side by side");

// ---- items ----
await col(0).locator(".row", { hasText: "Call the dentist" }).dragTo(col(0).locator(".row").first(), { targetPosition: { x: 80, y: 3 } }); await settle();
ok((await names(0))[0] === "Call the dentist", "item: reorder within a list");
await col(0).locator(".row", { hasText: "Read:" }).dragTo(col(0).locator(".row", { hasText: "Groceries" }), { targetPosition: { x: 80, y: 14 } }); await settle();
ok((await rows(0, "Groceries")).some(t => t.startsWith("Read:")) && !(await names(0)).some(t => t.startsWith("Read:")), "item: dropped onto an item -> becomes a sub-item line in ITS MARKDOWN");
await col(0).locator(".row", { hasText: "Reply to Sam" }).dragTo(col(1).locator(".row", { hasText: "Call the plumber" }), { targetPosition: { x: 80, y: 3 } }); await settle();
ok((await names(1)).some(t => t.startsWith("Reply to Sam")) && !(await names(0)).some(t => t.startsWith("Reply to Sam")), "item: moved between columns");
await col(0).locator(".row", { hasText: "Call the dentist" }).dragTo(p.locator("aside li[data-droplist]", { hasText: "Trip to Lisbon" })); await settle();
ok((await names(2)).includes("Call the dentist"), "item: dropped on a list name in the sidebar");

// dropping anywhere on an item's card (not just its name row) must nest into it, never fall through to "end of list"
await col(2).locator(".row", { hasText: "Call the dentist" }).dragTo(col(0).locator("li.item", { hasText: "Groceries" }).locator(".md").first(), { targetPosition: { x: 20, y: 6 } }); await settle();
const gr = await rows(0, "Groceries");
ok(gr.includes("Call the dentist") && !(await names(2)).includes("Call the dentist") && (await names(0)).every(n => n !== "Call the dentist"), "item dropped on an item's BODY text -> becomes its sub-item (not appended to the list): " + gr.slice(-2).join(" / "));
await col(0).locator("ul.check li", { hasText: "Call the dentist" }).dragTo(col(0).locator("li.item", { hasText: "Groceries" }).locator(".md").first(), { targetPosition: { x: 20, y: 6 } }); await settle();   // a row dragged onto its own card: stays a sub-item
ok((await rows(0, "Groceries")).includes("Call the dentist"), "sub-item dropped on its own item's body stays in that item");

// ---- sub-items ----
await p.reload(); await p.waitForSelector(".col");
let g = await rows(0, "Groceries"); console.log("   Groceries rows:", g);
await col(0).locator("ul.check li", { hasText: "coffee beans" }).dragTo(col(0).locator("ul.check li", { hasText: "oat milk" }), { targetPosition: { x: 40, y: 3 } }); await settle();
g = await rows(0, "Groceries"); ok(g.indexOf("coffee beans") < g.indexOf("oat milk"), "sub-item: reordered within its item");
await col(0).locator("ul.check li", { hasText: "oat milk" }).dragTo(col(2).locator("ul.check li", { hasText: "charger" }), { targetPosition: { x: 40, y: 3 } }); await settle();
ok((await rows(2, "Packing")).join("|").includes("oat milk|charger") && !(await rows(0, "Groceries")).includes("oat milk"), "sub-item: moved INTO another item (other column), above the target row");
await col(0).locator("ul.check li", { hasText: "something green" }).dragTo(col(0).locator(".row", { hasText: "Groceries" }), { targetPosition: { x: 80, y: 3 } }); await settle();
ok((await names(0)).includes("something green") && !(await rows(0, "Groceries")).includes("something green"), "sub-item: dragged OUT, becomes an item of its own");
await col(2).locator(".row", { hasText: "Stay" }).dragTo(col(2).locator("ul.check li", { hasText: "sunscreen" }), { targetPosition: { x: 40, y: 20 } }); await settle();
const pk = await rows(2, "Packing"); ok(pk.includes("Stay") && !(await names(2)).includes("Stay") && pk.indexOf("Stay") > pk.indexOf("sunscreen"), "item dropped onto a sub-item row -> becomes a sub-item below it");
await p.reload(); await p.waitForSelector(".col");
ok((await rows(2, "Packing")).includes("Stay") && (await names(0)).includes("something green"), "everything survives a reload");
await p.screenshot({ path: process.argv[2] + "-board.png" });

// ---- views ----
await p.click("aside li a >> text=Home renovation"); await p.waitForFunction(() => document.querySelector("header.pagehead h2")?.textContent.trim() === "Home renovation");
ok(await p.locator(".col").count() === 0, "opening a list shows the single-list view");
await p.check("aside li:has-text('Trip to Lisbon') input.pick"); await p.waitForTimeout(300);
ok(await p.locator(".col").count() === 2, "ticking a second list shows exactly those two side by side");
await p.click("aside >> text=All lists"); await p.waitForTimeout(300);
ok(await p.locator(".col").count() === 3, "'All lists' returns to the board");
console.log(errs.join("\n") || "no page errors"); await b.close(); process.exit(fails ? 1 : 0);
