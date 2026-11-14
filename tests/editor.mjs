// Plain editor: click title -> one textarea; Ctrl+Enter saves; Esc cancels; Enter adds in the add box; links render and don't open the editor.
import { chromium } from "playwright-core";
const b = await chromium.launch({ executablePath: process.env.CHROMIUM || "/usr/bin/chromium", args: ["--no-sandbox"] });
const p = await (await b.newContext({ viewport: { width: 1300, height: 800 } })).newPage();
const errs = []; p.on("pageerror", e => errs.push(e.message));
let fails = 0; const ok = (c, m) => { console.log(c ? "ok  " : "FAIL", m); if (!c) fails++; };
await p.goto("http://localhost:8000/"); await p.waitForSelector("aside");
await p.fill("aside input[name=name]", "Notes"); await p.press("aside input[name=name]", "Enter"); await p.waitForSelector(".col");
await p.fill(".col form.add textarea", "Plan **trip**"); await p.press(".col form.add textarea", "Enter");               // Enter adds
await p.waitForSelector("li.item"); ok(await p.locator("li.item .name strong").count() === 1, "Enter in the add box adds; **bold** renders in the title");
await p.fill(".col form.add textarea", "line one"); await p.press(".col form.add textarea", "Shift+Enter"); await p.keyboard.type("line two");
ok(await p.locator("li.item").count() === 1, "Shift+Enter does not submit");
await p.press(".col form.add textarea", "Control+Enter"); await p.waitForFunction(() => document.querySelectorAll("li.item").length === 2);
ok(true, "Ctrl+Enter adds too");
// edit
await p.locator("li.item .name").first().click({ position: { x: 4, y: 4 } }); await p.waitForSelector(".editor textarea");
ok(await p.locator(".ed-bar, .ed-preview, .ed-title, [data-md]").count() === 0, "no toolbar, preview or title field");
ok(await p.locator(".editor textarea").evaluate(e => document.activeElement === e), "textarea is focused");
await p.fill(".editor textarea", "Plan _the_ trip, see https://example.com/x and **more**\nsecond line"); await p.press(".editor textarea", "Control+Enter");
await p.waitForFunction(() => !document.querySelector(".editor"));
const first = p.locator("li.item").first();
ok(await first.locator(".name em").count() === 1 && await first.locator(".name strong").count() === 1, "title renders _italic_ and **bold**");
const a = first.locator(".name a"); ok(await a.count() === 1 && await a.getAttribute("target") === "_blank" && (await a.getAttribute("rel")).includes("noopener"), "URL becomes a safe link");
await a.click({ modifiers: [], noWaitAfter: true, trial: true }).catch(() => {});
ok(await p.locator(".editor").count() === 0, "link inside the title does not open the editor");
ok((await first.locator(".md").textContent()).includes("second line"), "rest of the text renders as body");
// cancel
await p.locator("li.item .name").first().click({ position: { x: 4, y: 4 } }); await p.waitForSelector(".editor textarea"); await p.fill(".editor textarea", "SHOULD NOT SAVE"); await p.press(".editor textarea", "Escape");
await p.waitForFunction(() => !document.querySelector(".editor"));
ok(!(await p.textContent("#main")).includes("SHOULD NOT SAVE"), "Esc cancels without saving");
// cursors
const cur = (sel) => p.locator(sel).first().evaluate(e => getComputedStyle(e).cursor);
ok(await cur("li.item .row") === "grab", "row: grab"); ok(await cur("li.item .row input[type=checkbox]") === "pointer", "checkbox: pointer");
ok(await cur("li.item .name") === "text", "title: text (click to edit)"); ok(await cur(".col > header a") === "pointer", "list name: pointer");
console.log(errs.join("\n") || "no page errors"); await b.close(); process.exit(fails ? 1 : 0);
