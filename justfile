web:
  cd backend && uv run lawrag start

initdb:
  cd backend && uv run lawrag database init

ui:
  cd frontend && pnpm dev

build-ui:
  cd frontend && pnpm build
  rm -rf backend/static
  cp -r frontend/dist backend/static

database:
  cd docker && podman-compose up database

web-docker:
  cd docker && podman-compose up web

docker:
  cd docker && podman-compose up

backend-format:
  cd backend && uv run ruff format
backend-lint:
  cd backend && uv run ruff check --fix
backend-typecheck:
  cd backend && uv run ty check --fix

frontend-check:
  cd frontend && pnpm check --write
frontend-typecheck:
  cd frontend && pnpm type-check

ingest-dir DIR="" CATEGORY="":
  cd backend && uv run lawrag ingest dir {{DIR}} --category {{CATEGORY}}
