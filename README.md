# ToDoing

Todo lists in the browser. Items are markdown, the first line is the title and `* [ ]` lines are sub-items.
Lists can be hidden, colour-grouped, dragged around and connected with strings.

It is a static site: HTMX for the UI and Python (Pyodide) for all logic. Your data lives in a private GitHub repo
named `_todoing_data_`. There is no backend. Design notes and measurements are in [PLAN.md](PLAN.md).

## Run locally
```bash
python scripts/serve.py
```
This builds `dist/` and serves http://localhost:8000. Without signing in everything is stored in the browser.

## Test
```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
scripts/test.sh          # lint, unit and git sync tests (what CI runs)
scripts/test.sh fuzz     # adds the multi-device fuzzer
```
Browser tests need headless Chromium and `npm i` inside `tests/`. Start `python scripts/serve.py` first, then run any
`node tests/<name>.mjs`. `e2e.mjs` also needs `python tests/mock_github_server.py 9000`.

## Deploy to GitHub Pages
1. Push this folder to a GitHub repo on branch `main`.
2. In the repo settings, set Pages, Source to **GitHub Actions**.

Every push to `main` runs the tests, builds and publishes to `https://<user>.github.io/<repo>/`.

## Connect GitHub
1. Open the site and click **Sign in**.
2. Create the private repo `_todoing_data_` (first device only, the dialog links to the prefilled page).
3. Create a fine-grained token limited to that repo with *Contents: Read and write* and paste it.

## Add another device
On a signed-in device click **Add device** and scan the QR code. You can also copy the link or the key and paste it into
**Sign in**. The key contains the access token, so treat it like a password. To revoke a device, delete the token on GitHub.
