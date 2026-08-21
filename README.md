# MedFlowAI

The frontend demo for the MedFlowAI clinical documentation workflow, plus a
backend that persists uploaded documents to object storage.

Everything in the app is still fixture-driven **except document upload**, which
now writes the real file to an S3-compatible bucket. See
[backend/README.md](backend/README.md).

## Install and Run

Requirements: Node.js `>=18.18.0` and npm `>=9.0.0`.

```bash
npm install
npm run dev
```

The local app is available at `http://localhost:5173`.

To exercise document upload for real, start the backend as well (Python 3.12,
Docker):

```bash
cp .env.example .env
docker compose up -d
./scripts/run_backend.sh
```

The Vite dev server proxies `/api` and `/health` to `http://localhost:8000`, so
nothing else needs configuring. Without the backend running, the upload page
still works against its fixtures — it just does not store anything, and the
storage indicator in the page header says so.

To confirm an uploaded document actually reached the bucket:

```bash
./scripts/verify_minio_upload.sh
```

Useful project checks:

```bash
npm run lint
npm test
npm run build
```

## Current Demo / Hardcoded Behavior

### Demo Login

```text
Email: admin@gmail.com
Password: 1234
```

This is a frontend-only credential check in `src/components/login-form.tsx`. There is no real authentication, backend auth, JWT, OAuth, database user validation, or auth API.

On success, the app writes `medflow.demo-session=active` to browser `sessionStorage` through `src/lib/demoSession.ts` and opens the existing dashboard at `/`. The root route checks this flag in `src/App.tsx`. The sign-up form only redirects to login with a demo status message; it does not create an account.

### Demo Patients and Clinical Data

Patient records are fixture data in `src/mocks/patients.json` and are loaded by `src/api/patients.ts`:

| Patient ID | Name | Encounter | Status |
| --- | --- | --- | --- |
| `pat_00123` | Ananya Mehta | `enc_2026_0817_01` | active |
| `pat_00456` | Ananya Malhotra | `enc_2026_0818_02` | active |
| `pat_00999` | Rahul Sharma | `enc_context_01` | active |

The Step 1 extraction fixture is `src/mocks/step1-output.json`, returned by the local functions in `src/api/step1.ts`:

- Job `job_ocr_771`, document `doc_5521`, patient `pat_00123`, and encounter `enc_2026_0817_01`.
- Source file `Ananya_Mehta_prescription_2026-08-17.jpg`, Hindi input, translation confidence `0.94`, and initial processing status `pending_human_verification`.
- Extracted fields: Amoxicillin (`0.83`, `review_required`), Metformin (`0.96`, `approved`), dosage strength `500 mg` (`0.91`, `review_required`), and frequency `twice daily` (`0.78`, `pending`).
- The review-required fields have `requires_doctor_review_before_memory_write: true`; the approved Metformin field has it set to `false`.

Clinical NLP data is fixture data in `src/mocks/clinical-events.json`. `src/api/pipeline.ts` returns six records for `pat_00123` / `enc_2026_0817_01`: Metformin 500 mg twice daily, a 500 mg dosage, twice-daily frequency, no history of diabetes, HbA1c 7.2%, and a possible penicillin allergy. The first five are `valid`; the penicillin allergy is `incomplete_provenance`. The fixture contains the model confidence values, including `0.71` BioClinicalBERT and `0.68` Gemini contextualization confidence for the penicillin allergy.

Memory and conflict demo data is in `src/mocks/retrieved-context.json` and `src/mocks/memory-events.json`:

- Verified context: Hypertension, Metformin 500 mg, no known drug allergies, and Hemoglobin A1c measurement.
- Unverified context: a possible penicillin allergy and a current Metformin 1000 mg record, both trust tier 3; `conflict_001` is a high-risk unresolved allergy conflict.
- Static history contains Metformin 500 mg, Metformin 1000 mg, and a discontinued Metformin record in `src/mocks/memory-events.json`.

### Other Frontend-Only Assumptions

- `src/api/step1.ts`, `src/api/patients.ts`, `src/api/pipeline.ts`, and `src/api/sourceDocuments.ts` are local mock services. They use in-memory state, simulated delays, resolved fixture promises, and browser-openable data URLs instead of network calls.
- Step 1 verification mutates module memory only. It returns the synthetic audit ID `aud_9910`; it is not persisted.
- Clinical NLP validation returns the input unchanged. Memory writes, retrieval, conflict resolution, tier approval/rejection, and document generation return fixture or synthetic responses from `src/api/pipeline.ts`.
- Patient creation appends to an in-memory array and derives the next ID locally. It is lost on reload.
- Generated document history is held in the module-level `documentHistory` array in `src/api/pipeline.ts`.
- The frontend uses physician ID `phy_04` in verification, clinical NLP actions, and document finalization.
- `src/api/sourceDocuments.ts` uses hardcoded document metadata and data URLs, including `doc_5521`, `abha_seed_001`, and the prior medication records `doc_prior_001`, `doc_prior_002`, and `doc_prior_003`.
- Dashboard recent activity is partly static in `src/pages/DashboardPage.tsx`: Ananya Mehta, Vikram Singh with `Lab_Report_2026-08-17.pdf`, and Sara Thomas with `Discharge_Note_0817.pdf`. The dashboard also has a fallback display of `4 fields need your review`.
- Default patient, encounter, document, and query values are embedded in `src/context/WorkflowContext.tsx`, `src/hooks/useMemory.ts`, and `src/pages/DocumentationPage.tsx`, including `pat_00123`, `enc_2026_0817_01`, and `doc_5521`.

## Replacing Demo Auth

Current flow:

```text
Login
  ↓
hardcoded email/password check
  ↓
local demo session
  ↓
existing dashboard
```

The demo credential check and navigation are in `src/components/login-form.tsx`. The session flag is implemented in `src/lib/demoSession.ts`, and the root-route session gate is in `src/App.tsx`.

Replace the demo credential check in `src/components/login-form.tsx` with the backend authentication API once the backend endpoint/contract is finalized.

The replacement flow should be:

```text
Login
  ↓
POST backend auth endpoint
  ↓
backend validates credentials
  ↓
receive authentication/session token
  ↓
store session securely
  ↓
navigate to dashboard
```

There is currently no HTTP API client or authentication service. The existing service boundary is the local function barrel in `src/api/index.ts`, consumed through React Query hooks in `src/hooks/`.

## Backend / AI Integration Points

### Step 1 Extraction and Physician Review

```text
Current frontend source:
src/api/documentStorage.ts   (real -- posts to the backend)
src/api/step1.ts             (mock -- extraction and review)
src/mocks/step1-output.json

Current behavior:
Document upload is implemented. When a physician picks a file on the upload
page, src/api/documentStorage.ts posts it to the backend, which stores the
bytes in the MinIO bucket and returns the object key and checksum. The page
renders that as a "Stored in object storage" receipt.

Everything after storage is still fixture-driven. No OCR, extraction, or AI
runs, and verification still mutates module-local state. With no file picked,
the page falls back to the mock upload functions in src/api/step1.ts, which is
what the existing tests exercise.

Future integration:
Replace the extraction and physician-review functions in src/api/step1.ts with
backend contracts. The storage path does not need replacing.
```

### Patients

```text
Current frontend source:
src/api/patients.ts
src/mocks/patients.json

Current behavior:
Search, lookup, and patient creation operate on an in-memory fixture array.

Future integration:
Replace the local patient functions with the patient search, lookup, and create service. Backend endpoint/contract to be provided by the backend team.
```

### Clinical NLP and AI Responses

```text
Current frontend source:
src/api/pipeline.ts
src/mocks/clinical-events.json

Current behavior:
processStep2 and getStep2Job always return the same clinical-event fixture. Validation is a pass-through and does not call an AI service.

Future integration:
Replace the fixture response with the backend/AI extraction, normalization, confidence, provenance, and validation response. Backend endpoint/contract to be provided by the backend team.
```

### Patient Memory and Conflicts

```text
Current frontend source:
src/api/pipeline.ts
src/mocks/retrieved-context.json
src/mocks/memory-events.json
src/mocks/memory-write-response.json

Current behavior:
Retrieval, memory events, memory writes, conflict resolution, and trust-tier actions return static or synthetic responses. No clinical database is connected.

Future integration:
Replace these functions with backend memory retrieval, append-only event, conflict, and physician decision services. Backend endpoint/contract to be provided by the backend team.
```

### Clinical Document Generation

```text
Current frontend source:
src/api/pipeline.ts
src/mocks/soap-document.json
src/mocks/discharge-document.json

Current behavior:
SOAP and discharge drafts are selected from fixtures. Finalization updates module-local document history and returns a synthetic memory-write payload.

Future integration:
Replace generation, review, finalization, and memory handoff with backend/AI document services. Backend endpoint/contract to be provided by the backend team.
```

### Source Documents

```text
Current frontend source:
src/api/sourceDocuments.ts

Current behavior:
The fixture documents (doc_5521, abha_seed_001, the doc_prior_* records) are
still hardcoded metadata plus data URLs.

Documents uploaded during this session are a separate, real path:
GET /api/v1/step1/documents/{document_id}/source returns a short-lived
presigned URL to the stored object.

Future integration:
Point the fixture lookups at the same retrieval endpoint once the fixture
documents themselves live in the bucket.
```

> Before integrating backend/auth/AI services, replace the documented demo/mock values rather than building new functionality around them. The current values exist only to support the frontend demo.
