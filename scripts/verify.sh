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
# NEXT_PUBLIC_*は必須(未設定だとビルドが止まる)。ここではビルドが通るかだけを見るので、
# 手元の.env.localに左右されないよう、ダミー値を明示的に渡す(process.envが.env.localより優先)。
(cd web && NEXT_PUBLIC_API_BASE_URL=https://api.example.invalid \
  NEXT_PUBLIC_STAFF_CLIENT_ID=dummy-client-id npm run build)

echo "== [infra] Build =="
(cd infra && bun run build)

echo "== [infra] CDK synth =="
(cd infra && bunx cdk synth)

echo "== [infra] Tests =="
(cd infra && bun run test)

echo "All verification checks passed."
