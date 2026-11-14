// Pyodide host. JS only does: boot, IndexedDB key/value, message RPC. All logic lives in Python.
import { loadPyodide } from "../vendor/pyodide/pyodide.mjs";

const base = new URL("../", import.meta.url);
const db = new Promise((res, rej) => {
  const r = indexedDB.open("ghtodo", 1);
  r.onupgradeneeded = () => r.result.createObjectStore("kv");
  r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error);
});
const tx = async (mode, f) => { const d = await db; return new Promise((res, rej) => {
  const q = f(d.transaction("kv", mode).objectStore("kv")); q.onsuccess = () => res(q.result); q.onerror = () => rej(q.error); }); };
const host = {
  idbGet: (k) => tx("readonly", s => s.get(k)),
  idbSet: (k, v) => tx("readwrite", s => s.put(v, k)),
  idbDel: (k) => tx("readwrite", s => s.delete(k)),
};

// Anything Pyodide throws outside a promise chain would otherwise leave the page on the spinner forever.
const fatal = (e) => self.postMessage({ fatal: String(e?.reason?.message || e?.reason || e?.message || e) });
self.addEventListener("unhandledrejection", fatal); self.addEventListener("error", fatal);

let py, bridge, chain = Promise.resolve();
const ready = (async () => {
  py = await loadPyodide({ indexURL: new URL("vendor/pyodide/", base).href });
  const manifest = await (await fetch(new URL("manifest.json", base))).json();
  for (const url of ["app.zip", ...manifest.wheels]) {
    const buf = await (await fetch(new URL(url, base))).arrayBuffer();
    py.unpackArchive(buf, url.endsWith(".whl") ? "wheel" : "zip", { extractDir: "/lib" });
  }
  py.runPython("import sys; sys.path.insert(0, '/lib')");
  bridge = py.pyimport("ghtodo.bridge");
  return await bridge.init(host);
})();

// One request at a time: a sync can never interleave with an edit.
self.onmessage = (e) => {
  const { id, op, args } = e.data;
  chain = chain.then(async () => {
    try {
      const signedIn = await ready;
      const result = op === "ready" ? signedIn : await bridge[op](...args);
      self.postMessage({ id, result });
    } catch (err) { self.postMessage({ id, error: String(err) }); }
  });
};
