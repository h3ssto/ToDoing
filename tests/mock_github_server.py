"""Local stand-in for api.github.com backed by a REAL git repo (tests/localgit.py).  python tests/mock_github_server.py [port]
Implements /user, /repos/<u>/_todoing_data_ and the Git Data API subset used by sync.py, with CORS."""
import asyncio, json, pathlib, sys, tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from localgit import LocalGit

REPO = tempfile.mkdtemp(prefix="mockgh-"); GH = LocalGit(REPO, empty="--empty" in sys.argv)
CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*", "Access-Control-Allow-Methods": "GET,POST,PATCH,PUT,DELETE"}


class H(BaseHTTPRequestHandler):
    def _send(self, st, obj):
        b = json.dumps(obj).encode(); self.send_response(st)
        for k, v in {**CORS, "Content-Type": "application/json"}.items(): self.send_header(k, v)
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_OPTIONS(self): self.send_response(204); [self.send_header(k, v) for k, v in CORS.items()]; self.end_headers()
    def _do(self):
        n = int(self.headers.get("Content-Length") or 0); body = json.loads(self.rfile.read(n)) if n else None
        if not self.headers.get("Authorization", "").startswith("Bearer "): return self._send(401, {"message": "no token"})
        p = self.path
        if p == "/user": return self._send(200, {"login": "tester"})
        if p == "/repos/tester/_todoing_data_": return self._send(200, {"full_name": "tester/_todoing_data_", "private": True, "default_branch": "main"})
        if "/git/" in p or "/contents/" in p:
            st, out = asyncio.run(GH(self.command, "https://api.github.com" + p, body)); return self._send(st, out)
        self._send(404, {"message": "not found " + p})
    do_GET = do_POST = do_PATCH = do_PUT = _do
    def log_message(self, *a): pass


if __name__ == "__main__":
    port = int(next((a for a in sys.argv[1:] if a.isdigit()), 9000))
    print("mock github on", port, "repo", REPO, flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
