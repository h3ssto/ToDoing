#!/usr/bin/env python3
"""Build and serve dist/ from the right place no matter where you run it:  python scripts/serve.py [port]"""
import http.server, pathlib, socketserver, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
subprocess.run([sys.executable, str(ROOT / "scripts" / "build.py")], check=True)
handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(ROOT / "dist"), **k)
socketserver.TCPServer.allow_reuse_address = True
with socketserver.ThreadingTCPServer(("127.0.0.1", port), handler) as srv:
    print(f"serving {ROOT / 'dist'} on http://localhost:{port}  (Ctrl+C to stop)")
    srv.serve_forever()
