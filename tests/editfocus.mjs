// Regression: typing in one editor must never jump to another editor (status poll / hover swaps), and selected text stays visible.
import { chromium } from "playwright-core";
const b = await chromium.launch({ executablePath: process.env.CHROMIUM || "/usr/bin/chromium", args: ["--no-sandbox"] });
const p = await (await b.newContext({ viewport: { width: 1300, height: 800 } })).newPage();
let fails = 0; const ok = (c, m) => { console.log(c ? "ok  " : "FAIL", m); if (!c) fails++; };
await p.goto("http://localhost:8000/?demo"); await p.waitForSelector("li.item");
await p.locator("li.item .name").nth(0).click(); await p.waitForSelector(".editor textarea");
await p.locator("li.item .name").nth(1).click(); await p.waitForFunction(() => document.querySelectorAll(".editor textarea").length === 2);
const second = p.locator(".editor textarea").nth(1);
ok(await second.evaluate(e => document.activeElement === e), "newest editor has focus");
await second.click(); await p.keyboard.type("a b"); await p.keyboard.press("Space"); await p.keyboard.press("Backspace");
await p.waitForTimeout(12000);                                   // status poll (5 s) fires meanwhile
await p.keyboard.type(" xyz");
ok(await second.evaluate(e => document.activeElement === e && e.value.endsWith("a b xyz")), "typing stays in the editor I clicked");
ok(await p.locator(".editor textarea").nth(0).evaluate(e => !e.value.includes("xyz")), "first editor untouched");
await second.press("Control+a"); await p.screenshot({ path: "/tmp/sel.png" });
const wrap = second.locator("xpath=..");
const px = await wrap.evaluate(el => { const h = el.querySelector(".hl"), t = el.querySelector("textarea");
  return [getComputedStyle(h).zIndex, getComputedStyle(h).backgroundColor, getComputedStyle(t).backgroundColor]; });
ok(px[0] === "2" && px[1] === "rgba(0, 0, 0, 0)", "styled text layer is above and transparent: " + px.join(" | "));
await b.close(); process.exit(fails ? 1 : 0);
