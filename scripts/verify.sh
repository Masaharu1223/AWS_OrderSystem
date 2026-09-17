#!/usr/bin/env bash
set -euo pipefail

echo "== [services] Lint (ruff) =="
(cd services && source .venv/bin/activate && ruff check .)

echo "== [services] Type check (mypy) =="
(cd services && source .venv/bin/activate && mypy src)

echo "== [services] Unit / integration tests (pytest) =="
(cd services && source .venv/bin/activate && pytest)

echo "== [web] Lint (eslint) =="
(cd web && npm run lint)

echo "== [web] Build =="
(cd web && npm run build)

echo "== [infra] Build =="
(cd infra && bun run build)

echo "== [infra] CDK synth =="
(cd infra && bunx cdk synth)

echo "== [infra] Tests =="
(cd infra && bun run test)

echo "All verification checks passed."
