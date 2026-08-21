#!/usr/bin/env bash
# End-to-end check that an uploaded document reaches the MinIO bucket.
#
# It uploads a file through the backend, then reads the object back out of
# MinIO with the AWS SDK -- deliberately not through the backend, so a backend
# that reported success without writing anything would be caught here.
set -euo pipefail

cd "$(dirname "$0")/.."

API="${API:-http://localhost:8000}"
PATIENT_ID="${PATIENT_ID:-pat_00123}"
ENCOUNTER_ID="${ENCOUNTER_ID:-enc_2026_0817_01}"
PYTHON=backend/.venv/bin/python

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
fail() { printf '\033[31mFAIL: %s\033[0m\n' "$1" >&2; exit 1; }

step "1. Backend health"
HEALTH=$(curl -fsS "$API/health") || fail "backend is not responding at $API"
echo "$HEALTH"
case "$HEALTH" in
  *'"persistent":true'*) ;;
  # Mock storage returns 200 on every upload while persisting nothing, which
  # is exactly the false pass this script exists to prevent.
  *) fail "backend is NOT on persistent storage. Set STEP1_STORAGE_MODE=s3 in .env." ;;
esac

step "2. Uploading a test document"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
SAMPLE="$TMP/verification-note.txt"
printf 'MedFlow storage verification\nUploaded at %s\n' "$(date -u +%FT%TZ)" > "$SAMPLE"
EXPECTED_SHA=$(shasum -a 256 "$SAMPLE" | cut -d' ' -f1)

RESPONSE=$(curl -fsS -X POST "$API/api/v1/step1/documents/typed" \
  -F "file=@$SAMPLE;type=text/plain" \
  -F "patient_id=$PATIENT_ID" \
  -F "encounter_id=$ENCOUNTER_ID" \
  -F "source_language=en") || fail "upload was rejected"
echo "$RESPONSE"

KEY=$($PYTHON -c 'import json,sys; print(json.load(sys.stdin)["stored"]["key"])' <<<"$RESPONSE")
BUCKET=$($PYTHON -c 'import json,sys; print(json.load(sys.stdin)["stored"]["bucket"])' <<<"$RESPONSE")
DOCUMENT_ID=$($PYTHON -c 'import json,sys; print(json.load(sys.stdin)["document_id"])' <<<"$RESPONSE")

step "3. Reading the object straight out of MinIO"
$PYTHON - "$BUCKET" "$KEY" "$EXPECTED_SHA" <<'PY'
import hashlib
import os
import sys

import boto3
from botocore.config import Config
from dotenv import load_dotenv

load_dotenv(".env")
bucket, key, expected_sha = sys.argv[1], sys.argv[2], sys.argv[3]

client = boto3.client(
    "s3",
    region_name=os.getenv("S3_REGION", "us-east-1"),
    endpoint_url=os.getenv("S3_ENDPOINT_URL"),
    aws_access_key_id=os.getenv("S3_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("S3_SECRET_ACCESS_KEY"),
    config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
)
body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
actual_sha = hashlib.sha256(body).hexdigest()

print(f"  bucket   {bucket}")
print(f"  key      {key}")
print(f"  bytes    {len(body)}")
print(f"  sha256   {actual_sha}")
if actual_sha != expected_sha:
    raise SystemExit(f"FAIL: bucket contents differ from the uploaded file ({expected_sha})")
print("  contents match the uploaded file")
PY

step "4. Presigned retrieval through the backend"
SOURCE=$(curl -fsS "$API/api/v1/step1/documents/$DOCUMENT_ID/source") || fail "retrieval failed"
URL=$($PYTHON -c 'import json,sys; print(json.load(sys.stdin)["download_url"])' <<<"$SOURCE")
curl -fsS "$URL" > "$TMP/downloaded" || fail "the presigned URL did not resolve"
diff -q "$SAMPLE" "$TMP/downloaded" >/dev/null || fail "downloaded bytes differ from the upload"
echo "  presigned URL returned the original document"

printf '\n\033[32mPASS: the uploaded document is in the MinIO bucket.\033[0m\n'
printf 'Browse it at http://localhost:%s (bucket: %s)\n' "${MINIO_CONSOLE_PORT:-9001}" "$BUCKET"
