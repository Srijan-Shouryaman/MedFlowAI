# MedFlow AI Backend

Persists uploaded clinical documents to an S3-compatible bucket.

That is the whole scope. There is no authentication, no database, no OCR, no
extraction, and no clinical processing here. The frontend remains mock-backed
for everything else; only the upload path talks to a real server.

## Why this exists

`src/api/step1.ts` in the frontend returns fixture IDs and throws the chosen
file away. This service stores the actual bytes, so a document uploaded today
is still readable after a restart.

## Run it

From the repository root:

```bash
cp .env.example .env
docker compose up -d
./scripts/run_backend.sh
```

`docker compose up -d` starts MinIO and creates the bucket. `run_backend.sh`
creates `backend/.venv` on first run and starts uvicorn on port 8000. The Vite
dev server proxies `/api` and `/health` there, so `npm run dev` needs no extra
configuration.

Interactive API docs: <http://localhost:8000/docs>
MinIO console: <http://localhost:9001>

## Confirm a document reached the bucket

```bash
./scripts/verify_minio_upload.sh
```

The script uploads a file through the API and then reads the object back out of
MinIO with the AWS SDK **directly**, bypassing the backend. That matters: a
backend that returned success without writing anything would still pass a check
that only asked the backend what it stored.

It aborts up front if `/health` reports `persistent: false`, because in-memory
storage returns 200 on every upload while persisting nothing.

In the UI, uploading a real file shows a "Stored in object storage" panel with
the bucket, object key, and SHA-256 — enough to find the object by hand in the
MinIO console.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Storage backend, bucket, and whether it is persistent |
| `POST` | `/api/v1/step1/documents/typed` | Store a typed document |
| `POST` | `/api/v1/step1/documents/handwritten` | Store a handwritten document |
| `POST` | `/api/v1/step1/documents/multilingual` | Store a multilingual document |
| `GET` | `/api/v1/step1/documents` | Documents uploaded since startup |
| `GET` | `/api/v1/step1/documents/{document_id}/source` | Short-lived presigned download URL |

All three upload endpoints take the same multipart body: `file`, `patient_id`,
`encounter_id`, and `source_language`. They differ only in the modality they
record. They are separate routes rather than one route with a modality field
because the frontend already calls three distinct functions, and because each
will diverge once extraction exists.

### Status codes

| Code | Meaning |
| --- | --- |
| `201` | Stored |
| `400` | Unsafe filename, unsafe `patient_id`, or empty file |
| `413` | Larger than `MAX_UPLOAD_SIZE_BYTES` |
| `415` | Type not allowed, or the bytes do not match the declared type |
| `503` | Storage unreachable — **the upload was not saved** |

A storage failure is a 503, never a 201 with a failed status. The latter would
tell the caller the file was accepted and something went wrong afterwards,
which is not what happened.

## Layout

```
backend/app/
├── main.py              FastAPI app, CORS, startup wiring
├── api/
│   ├── documents.py     Upload and retrieval routes
│   ├── schemas.py       Request/response models
│   └── dependencies.py  Storage and registry injection
├── storage/             The object storage boundary
│   ├── base.py          ObjectStorage protocol + StoredObject
│   ├── s3.py            MinIO / AWS S3, retries, presigning
│   ├── mock.py          In-process dict, for tests
│   ├── keys.py          Object key construction
│   ├── factory.py       Backend selection from the environment
│   ├── config.py        Environment helpers
│   └── errors.py        Storage error hierarchy
├── upload_security.py   Size, MIME, and magic-byte validation
├── registry.py          In-memory document index (stand-in for a database)
├── services/            Placeholder — see services/README.md
└── db/                  Placeholder — see db/README.md
```

Callers depend on the `ObjectStorage` protocol, never on `S3ObjectStorage`
directly. That is what keeps MinIO a configuration choice rather than a code
dependency.

### Object keys

```
step1/patients/{patient_id}/documents/{document_id}/source
```

A pure function of `(patient_id, document_id)`, so an object can be located
without a database lookup. Keys carry no PHI: no original filename, no patient
name, no timestamp. They end up in logs and presigned URLs, so only opaque
identifiers belong in them.

Changing this layout after objects exist orphans every document already stored.

### What is not persistent

`registry.py` keeps document metadata — which patient a document belongs to,
its original filename — in process memory. It is lost on restart. The objects
in MinIO are not. Replace `registry.py` with a real repository when the
database layer lands; keep the same three method names.

## Moving to AWS S3

No application code changes. In `.env`:

- clear `S3_ENDPOINT_URL`
- set `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY`, or leave both empty to use
  the instance role
- set `S3_REGION` and `S3_BUCKET`
- set `S3_SSE=AES256` (or `aws:kms` with `S3_SSE_KMS_KEY_ID`)

Before a real deployment, the bucket also needs Block Public Access, a
TLS-only bucket policy, versioning with a retention rule, a lifecycle rule for
incomplete multipart uploads, and an IAM policy scoped to `PutObject` /
`GetObject` / `HeadObject` — the application should not hold `CreateBucket` or
`DeleteObject`. None of that is configured by `docker-compose.yml`, which is a
local development convenience only.

## Tests

```bash
backend/.venv/bin/python -m pytest
```

40 tests, no network and no Docker required — they run against the in-memory
backend and a fake boto3 client.
