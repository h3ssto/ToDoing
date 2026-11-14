#!/usr/bin/env python3
"""Build dist/: copy web/, zip the Python package, vendor Pyodide+htmx+wheels (cached in .cache/), write manifest.json."""
import hashlib, json, shutil, sys, urllib.request, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST, CACHE = ROOT / "dist", ROOT / ".cache"
PYODIDE = "314.0.7"
HTMX = "2.0.11"
FA = "6.5.2"
QR = "1.4.4"
CDN = "https://cdn.jsdelivr.net"
PYODIDE_FILES = ["pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"]
WHEELS = {  # pinned pure-python wheels (url from PyPI)
    "mdurl-0.1.2-py3-none-any.whl": "https://files.pythonhosted.org/packages/b3/38/89ba8ad64ae25be8de66a6d463314cf1eb366222074cfda9ee839c56a4b4/mdurl-0.1.2-py3-none-any.whl",
    "uc_micro_py-2.0.0-py3-none-any.whl": "https://files.pythonhosted.org/packages/61/73/d21edf5b204d1467e06500080a50f79d49ef2b997c79123a536d4a17d97c/uc_micro_py-2.0.0-py3-none-any.whl",
    "linkify_it_py-2.2.0-py3-none-any.whl": "https://files.pythonhosted.org/packages/13/d4/1152d1c7ab42d8b908be64fd200ddc870dc9d4925e951198702084aa1a7d/linkify_it_py-2.2.0-py3-none-any.whl",
    "markdown_it_py-4.3.0-py3-none-any.whl": "https://files.pythonhosted.org/packages/c9/31/5f0ac2f1a1c67423c995c731a11cd4ad05d081a2be969d74f868bdb9cc70/markdown_it_py-4.3.0-py3-none-any.whl",
}


def fetch(url: str, name: str) -> Path:
    CACHE.mkdir(exist_ok=True)
    p = CACHE / name
    if not p.exists():
        print("downloading", url)
        urllib.request.urlretrieve(url, p)
    return p


def main():
    shutil.rmtree(DIST, ignore_errors=True)
    shutil.copytree(ROOT / "web", DIST, ignore=shutil.ignore_patterns("py", "__pycache__"))
    # deterministic zip of the python package -> stable content hash
    with zipfile.ZipFile(DIST / "app.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted((ROOT / "web/py").rglob("*.py")):
            z.writestr(zipfile.ZipInfo(str(f.relative_to(ROOT / "web/py")), (2020, 1, 1, 0, 0, 0)), f.read_bytes())
    vp = DIST / "vendor/pyodide"; vp.mkdir(parents=True)
    for f in PYODIDE_FILES:
        shutil.copy(fetch(f"{CDN}/npm/pyodide@{PYODIDE}/{f}", f"pyodide-{PYODIDE}-{f}"), vp / f)
    shutil.copy(fetch(f"{CDN}/npm/htmx.org@{HTMX}/dist/htmx.min.js", f"htmx-{HTMX}.js"), DIST / "vendor/htmx.min.js")
    fa = DIST / "vendor/fa"; (fa / "css").mkdir(parents=True); (fa / "webfonts").mkdir()
    shutil.copy(fetch(f"{CDN}/npm/@fortawesome/fontawesome-free@{FA}/css/fontawesome.min.css", f"fa-{FA}-fontawesome.css"), fa / "css/fontawesome.min.css")
    shutil.copy(fetch(f"{CDN}/npm/@fortawesome/fontawesome-free@{FA}/css/solid.min.css", f"fa-{FA}-solid.css"), fa / "css/solid.min.css")
    shutil.copy(fetch(f"{CDN}/npm/@fortawesome/fontawesome-free@{FA}/webfonts/fa-solid-900.woff2", f"fa-{FA}-solid.woff2"), fa / "webfonts/fa-solid-900.woff2")
    shutil.copy(fetch(f"{CDN}/npm/qrcode-generator@{QR}/qrcode.js", f"qrcode-{QR}.js"), DIST / "vendor/qrcode.js")
    (DIST / "vendor/wheels").mkdir()
    for n, u in WHEELS.items():
        shutil.copy(fetch(u, n), DIST / "vendor/wheels" / n)
    files = sorted(p.relative_to(DIST).as_posix() for p in DIST.rglob("*") if p.is_file())
    py_files = [f for f in files if f.startswith("vendor/pyodide/")]
    app_files = [f for f in files if f not in py_files and not f.startswith("vendor/wheels/")]
    h = hashlib.sha256()
    for f in app_files + sorted(WHEELS):
        h.update(f.encode()); h.update((DIST / f).read_bytes() if (DIST / f).exists() else b"")
    manifest = {"version": h.hexdigest()[:12], "app": app_files + ["./"],
                "wheels": [f"vendor/wheels/{n}" for n in WHEELS],
                "pyodide": {"version": PYODIDE, "files": py_files}}
    (DIST / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print("built", manifest["version"], f"({len(files)} files)")


if __name__ == "__main__":
    sys.exit(main())
