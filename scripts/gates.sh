#!/usr/bin/env bash
# Canonical phase-gate runner for the remediation program.
#
# Usage:
#   scripts/gates.sh              # all three gates
#   scripts/gates.sh backend      # any subset: backend | frontend | dashboard
#
# Exit codes are per-gate and explicit; nothing is piped, so a red build can
# never hide behind a pipeline's last command. Backend resolves the project
# venv first — bare `pytest`/`python` are not on PATH on every machine.
set -u -o pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PY="$ROOT/backend/.venv/bin/python"
[[ -x "$PY" ]] || PY="$(command -v python3)" || { echo "no python3 found" >&2; exit 2; }

run_backend() {
  echo "=== gate: backend — JWT_SECRET=… $PY -m pytest -q ==="
  (cd "$ROOT/backend" && JWT_SECRET="${JWT_SECRET:-test}" "$PY" -m pytest -q)
}

run_frontend() {
  echo "=== gate: frontend — npm run build ==="
  (cd "$ROOT/frontend" && npm run build)
}

run_dashboard() {
  echo "=== gate: dashboard — npx next build ==="
  (cd "$ROOT/dashboard" && npx next build)
}

gates=("$@")
[[ ${#gates[@]} -eq 0 ]] && gates=(backend frontend dashboard)

# bash 3.2 (macOS default) compatible: no ${var^^}, no empty-array expansion.
overall=0
summary=""
for g in "${gates[@]}"; do
  case "$g" in
    backend)   run_backend;   code=$? ;;
    frontend)  run_frontend;  code=$? ;;
    dashboard) run_dashboard; code=$? ;;
    *) echo "unknown gate: $g (want backend|frontend|dashboard)" >&2; exit 2 ;;
  esac
  summary="${summary}$(echo "$g" | tr '[:lower:]' '[:upper:]')_EXIT=$code
"
  [[ $code -ne 0 ]] && overall=1
done

echo
printf '%s' "$summary"
if [[ $overall -eq 0 ]]; then echo "ALL GATES GREEN"; else echo "GATE FAILURE"; fi
exit $overall
