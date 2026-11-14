// Boot overlay: visible + cycling messages while Python loads (wasm artificially delayed), then gone; failure path shows an error.
import { chromium } from "playwright-core";
const b = await chromium.launch({ executablePath: process.env.CHROMIUM || "/usr/bin/chromium", args: ["--no-sandbox"] });
let fails = 0; const ok = (c, m) => { console.log(c ? "ok  " : "FAIL", m); if (!c) fails++; };
{ // slow boot
  const ctx = await b.newContext({ serviceWorkers: "block", viewport: { width: 900, height: 500 } }); const p = await ctx.newPage();
  await ctx.route("**/pyodide.asm.wasm", async r => { await new Promise(res => setTimeout(res, 4500)); r.continue(); });
  await p.goto("http://localhost:8000/", { waitUntil: "commit" });
  await p.waitForSelector("#boot:not(.gone)"); const m1 = await p.textContent("#boot-msg");
  if (process.argv[2]) await p.screenshot({ path: process.argv[2] });
  await p.waitForFunction(m => document.getElementById("boot-msg").textContent !== m, m1, { timeout: 4000 });
  ok(true, `messages rotate ("${m1}" → "${await p.textContent("#boot-msg")}")`);
  ok(await p.locator("#app aside").count() === 0, "page content is hidden/not rendered while loading");
  await p.waitForSelector("#app aside", { timeout: 30000 }); await p.waitForSelector("#boot", { state: "detached", timeout: 5000 });
  ok(true, "overlay disappears once the first render is ready");
  await ctx.close();
}
{ // failure
  const ctx = await b.newContext({ serviceWorkers: "block" }); const p = await ctx.newPage();
  await ctx.route("**/pyodide.asm.wasm", r => r.abort());
  await p.goto("http://localhost:8000/"); await p.waitForSelector("#boot.failed", { timeout: 30000 });
  ok(await p.isVisible("#boot-retry"), "failure shows an error and a Reload button: " + (await p.textContent("#boot-msg")).slice(0, 80));
  await ctx.close();
}
await b.close(); process.exit(fails ? 1 : 0);
