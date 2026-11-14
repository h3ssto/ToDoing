// Runs tests/bench_core.py inside REAL Pyodide (what the browser worker runs) using the built dist/.
import { loadPyodide } from "../dist/vendor/pyodide/pyodide.mjs";
import fs from "fs";
const D = new URL("../dist/", import.meta.url).pathname;
process.on("uncaughtException", e => { console.log("ERR", String(e.message || e).slice(0, 500)); process.exit(1); });
const t0 = performance.now();
const py = await loadPyodide({ indexURL: D + "vendor/pyodide/" });
const t1 = performance.now();
const m = JSON.parse(fs.readFileSync(D + "manifest.json"));
for (const u of ["app.zip", ...m.wheels]) py.unpackArchive(new Uint8Array(fs.readFileSync(D + u)), u.endsWith(".whl") ? "wheel" : "zip", { extractDir: "/lib" });
py.runPython("import sys; sys.path.insert(0,'/lib')");
const t2 = performance.now();
py.FS.writeFile("/lib/bench_core.py", fs.readFileSync(new URL("./bench_core.py", import.meta.url)));
py.runPython("import ghtodo.app");
const t3 = performance.now();
console.log(JSON.stringify({ boot_ms: { pyodide_runtime: t1 - t0, unpack_app_and_wheels: t2 - t1, import_ghtodo: t3 - t2 } }));
const sizes = process.argv.slice(2).join(",") || "100,1000,5000";
const out = py.runPython(`
import json, bench_core as b
from ghtodo import logfmt
logfmt.COMPACT_AFTER = 10**9
json.dumps({"scaling": b.run((${sizes},)), "log_length": b.run_log()})
`);
console.log(out);
