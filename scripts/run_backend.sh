#!/usr/bin/env bash
# Start the backend against local MinIO.
#
# Assumes `docker compose up -d` has already created the bucket and that a .env
# exists at the repo root (copy .env.example).
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "No .env found. Copy it first:  cp .env.example .env" >&2
  exit 1
fi

if [ ! -d backend/.venv ]; then
  echo "Creating backend/.venv ..."
  python3 -m venv backend/.venv
  backend/.venv/bin/pip install --quiet --upgrade pip
  backend/.venv/bin/pip install --quiet -r backend/requirements.txt
fi

cd backend
exec .venv/bin/uvicorn app.main:app --reload --port "${BACKEND_PORT:-8000}"
