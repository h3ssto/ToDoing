// Browser e2e (headless Chromium): connect -> edit -> sync -> 2nd device -> conflict, against tests/mock_github_server.py.
// usage: node tests/e2e.mjs <mock repo path> <screenshot.png>    (site on :8000 via scripts/serve.py, mock on :9000)
import { chromium } from "playwright-core";
import { execSync } from "child_process";
const REPO = process.argv[2];
const b = await chromium.launch({ executablePath: process.env.CHROMIUM || "/usr/bin/chromium", args: ["--no-sandbox"] });
const logs = [];
async function device(name) {
  const ctx = await b.newContext({ viewport: { width: 1100, height: 700 } });
  await ctx.route("https://api.github.com/**", async r => { const u = new URL(r.request().url());
    r.fulfill({ response: await r.fetch({ url: "http://127.0.0.1:9000" + u.pathname + u.search }) }); });
  const p = await ctx.newPage(); p.on("pageerror", e => logs.push(name + " pageerror: " + e.message)); p.on("console", m => m.type() === "error" && logs.push(name + " " + m.text().slice(0, 150)));
  await p.goto("http://localhost:8000/"); await p.waitForSelector("aside"); return p;
}
const connect = async (p) => { await p.click("#btn-login"); await p.fill("#pat", "github_pat_fake"); await p.click("dialog button[value=ok]");
  await p.waitForFunction(() => /synced|up to date/.test(document.getElementById("state").textContent), null, { timeout: 30000 }); return p.textContent("#state"); };
const A = await device("A");
console.log("A connect:", await connect(A));
await A.fill("aside input[name=name]", "Shared"); await A.press("aside input[name=name]", "Enter"); await A.waitForSelector("#board", { state: "attached" });
await A.fill("form.add textarea", "Buy milk\n* [ ] oat\n* [ ] soy"); await A.click("form.add button"); await A.waitForSelector("li.item");
await A.click("#btn-sync"); await A.waitForFunction(() => /synced/.test(document.getElementById("state").textContent));
console.log("A after edit+sync:", await A.textContent("#state"));
const B = await device("B");                         // second "device": fresh profile
console.log("B connect:", await connect(B));
await B.waitForSelector("aside li a"); await B.click("aside li a"); await B.waitForSelector("li.item .name");
console.log("B sees item:", await B.textContent("li.item .name"));
// conflicting edits: both edit the same item offline-ish, then sync
const edit = async (p, text) => { await p.click("li.item .name"); await p.fill("li.item textarea", text); await p.click("li.item form button:not([type=button])"); await p.waitForSelector("li.item .name"); };
await edit(A, "Buy milk\nA-WAS-HERE"); await edit(B, "Buy milk\nB-WAS-HERE");
await A.click("#btn-sync"); await A.waitForFunction(() => /synced/.test(document.getElementById("state").textContent));
await B.click("#btn-sync"); await B.waitForFunction(() => /conflict/.test(document.getElementById("state").textContent), null, { timeout: 20000 });
console.log("B after conflict sync:", await B.textContent("#state"));
console.log("B sidebar:", (await B.locator("aside li").allTextContents()).join(" | "), "| item now:", (await B.locator("li.item").first().textContent()).replace(/\s+/g, " "));
await B.click("aside li a >> text=Conflicts"); await B.waitForSelector(".conf"); await B.screenshot({ path: process.argv[3] });
console.log("commits:", execSync(`git --git-dir=${REPO} rev-list --count main`).toString().trim(), "files:", execSync(`git --git-dir=${REPO} ls-tree -r --name-only main`).toString().split("\n").join(" "));
console.log(logs.join("\n") || "no console errors");
await b.close();
