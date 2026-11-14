// Offline test: load once (service worker precaches everything), go offline, reload, data must still be there.
import { chromium } from "playwright-core";
const b = await chromium.launch({ executablePath: process.env.CHROMIUM || "/usr/bin/chromium", args: ["--no-sandbox"] });
const ctx = await b.newContext(); const p = await ctx.newPage(); const errs = [];
p.on("pageerror", e => errs.push(e.message));
await p.goto("http://localhost:8000/"); await p.waitForSelector("aside");
await p.waitForFunction(async () => (await navigator.serviceWorker.ready) && !!navigator.serviceWorker.controller, null, { timeout: 60000 });
console.log("caches:", await p.evaluate(async () => (await caches.keys()).join(", ")));
await p.fill("aside input[name=name]", "Offline test"); await p.press("aside input[name=name]", "Enter");
await p.waitForSelector(".col");
await p.fill("form.add textarea", "survives offline\n* [ ] a"); await p.click("form.add button"); await p.waitForSelector("li.item");
await ctx.setOffline(true);
const t0 = Date.now(); await p.reload(); await p.waitForSelector(".col", { timeout: 60000 });
await p.waitForSelector("li.item .name");
console.log("offline reload OK in", Date.now() - t0, "ms; item:", await p.textContent("li.item .name"), "| list:", await p.textContent(".col > header a"));
console.log(errs.join("\n") || "no page errors");
await b.close();
