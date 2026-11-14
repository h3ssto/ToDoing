// Strings across lists: connect via the UI, stubs show the other list's name, clicking it opens that list.
import { chromium } from "playwright-core";
const b = await chromium.launch({ executablePath: process.env.CHROMIUM || "/usr/bin/chromium", args: ["--no-sandbox"] });
const p = await (await b.newContext({ viewport: { width: 1500, height: 900 } })).newPage();
const errs = []; p.on("pageerror", e => errs.push(e.message));
let fails = 0; const ok = (c, m) => { console.log(c ? "ok  " : "FAIL", m); if (!c) fails++; };
await p.goto("http://localhost:8000/?demo"); await p.waitForSelector(".col");
const arm = async (colIdx, text) => { const row = p.locator(`.col >> nth=${colIdx} >> .row`, { hasText: text }); await row.hover(); await p.waitForTimeout(250);
  await row.locator("xpath=following-sibling::div[contains(@class,'tools')]").locator("button.link").click(); };
await arm(0, "Read:"); ok(await p.locator("button.link.armed").count() === 1, "first click arms the string (button highlighted)");
await arm(1, "Bathroom"); await p.waitForTimeout(400);
ok(await p.locator(".stub").count() === 0, "both lists visible: no stubs");
// demo data already has 3 same-list strings; ours is the one that starts at one column's edge and ends at the next column's edge
const crossPath = async () => (await p.locator(".cols > svg.strings path").evaluateAll(ps => ps.map(e => e.getAttribute("d"))))
  .filter(d => { const n = d.match(/-?[\d.]+/g).map(Number); return !d.includes("NaN") && n[0] < n[6] && n[6] - n[0] < 120 && Math.abs(n[1] - n[7]) > 0; });
ok((await crossPath()).length === 2, "both lists visible: the string itself is drawn across the columns");
await p.screenshot({ path: process.argv[2] || "/tmp/strings.png" });
await p.click("aside li a >> text=Today"); await p.waitForSelector("header.pagehead");     // hide the partner: only list 1
ok(await p.locator(".stub").count() === 2 && (await p.locator(".stub").allTextContents()).every(t => t.trim() === "Home renovation"), "partner list hidden: dashed stubs (existing + new string) name the other list");
ok(await p.locator(".detail > svg.strings path").count() === 0, "no drawn curve when the partner is hidden");
await p.locator(".stub").first().click();
await p.waitForFunction(() => document.querySelector("header.pagehead h2")?.textContent.trim() === "Home renovation", null, { timeout: 5000 }).catch(() => {});
ok((await p.textContent("header.pagehead h2")).trim() === "Home renovation", "clicking the stub opens the linked list");
ok(await p.locator(".stub").count() === 2 && (await p.locator(".stub").allTextContents()).every(t => t.trim() === "Today"), "opened list shows the stubs back");
await p.check("aside li:has-text('Today') input.pick"); await p.waitForTimeout(400);      // both again -> drawn
ok(await p.locator(".stub").count() === 0 && (await crossPath()).length === 2, "ticking the partner list again turns the stub into a drawn string");
await p.reload(); await p.waitForSelector("aside"); await p.click("aside li a >> text=Home renovation"); await p.waitForSelector("header.pagehead");
ok(await p.locator(".stub").count() === 2, "strings survive a reload");
console.log(errs.join("\n") || "no page errors"); await b.close(); process.exit(fails ? 1 : 0);
