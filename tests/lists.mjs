import { chromium } from "playwright-core";
const b = await chromium.launch({ executablePath: process.env.CHROMIUM || "/usr/bin/chromium", args: ["--no-sandbox"] });
const p = await (await b.newContext({ viewport: { width: 1300, height: 800 } })).newPage();
const errs = []; p.on("pageerror", e => errs.push(e.message));
let fails = 0; const ok = (c, m) => { console.log(c ? "ok  " : "FAIL", m); if (!c) fails++; };
await p.goto("http://localhost:8000/?demo"); await p.waitForSelector("li.item");
const li = (n) => p.locator("aside li[data-droplist]").nth(n);
// rename via pencil
await li(0).hover(); await li(0).locator(".ren").click();
await p.fill("aside input.rename", "Renamed"); await p.press("aside input.rename", "Enter");
await p.waitForFunction(() => document.querySelector("aside li[data-droplist] a").textContent.includes("Renamed"));
ok(true, "rename from sidebar");
await li(0).hover(); await li(0).locator(".ren").click(); await p.fill("aside input.rename", "Nope"); await p.press("aside input.rename", "Escape");
ok((await li(0).locator("a").textContent()).includes("Renamed"), "Esc cancels rename");
// rename via double-click on title in single-list view
await li(1).locator("a").click(); await p.waitForSelector(".detail h2");
await p.dblclick(".detail h2"); await p.fill("input.rename", "Reno"); await p.press("input.rename", "Enter");
await p.waitForFunction(() => document.querySelector(".detail h2")?.textContent.includes("Reno"));
ok(true, "rename by double-click on the title");
// delete only after hide, with two clicks
await p.click("aside li >> text=All lists");
await p.waitForSelector(".cols");
const n0 = await p.locator("aside li[data-droplist]").count();
await li(2).hover(); await li(2).locator("button[title=Hide]").click();
await p.waitForFunction(n => document.querySelectorAll("aside li[data-droplist]").length === n - 1, n0);
ok(await p.locator("aside li[data-droplist] .del").count() === 0, "no delete button on visible lists");
await p.click("aside .more a"); await p.waitForSelector("aside li.off");
const del = p.locator("aside li.off .del"); await p.locator("aside li.off").hover();
await del.click(); ok(await p.locator("aside li.off").count() === 1 && /Delete\?/.test(await del.textContent()), "first click only arms");
await del.click(); await p.waitForFunction(() => !document.querySelector("aside li.off"));
ok(await p.locator("aside .more").count() === 0, "second click deletes the list for good");
ok(errs.length === 0, "no page errors " + errs.join(";"));
await b.close(); process.exit(fails ? 1 : 0);
