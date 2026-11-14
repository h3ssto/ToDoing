#!/usr/bin/env bash
# Unit + sync tests (CI runs the same), optional fuzz:  scripts/test.sh [fuzz]
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PYTHON:-.venv/bin/python}
$PY -m pyflakes web/py tests scripts
$PY - <<'PYEOF'
import sys; sys.path.insert(0, "tests")
import test_core as c, test_sync as s
names = [n for n in dir(c) if n.startswith("test_")]
for n in names: getattr(c, n)()
sync_names = [n for n in dir(s) if n.startswith("test_")]
for n in sync_names: getattr(s, n)()
print(f"{len(names)} unit + {len(sync_names)} sync tests passed")
PYEOF
[ "${1:-}" = fuzz ] && $PY tests/fuzz.py 40 25 3
exit 0
