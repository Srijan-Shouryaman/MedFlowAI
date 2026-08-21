// The only real network calls in the app.
//
// Everything else under src/api is a local mock. This module posts the chosen
// file to the backend, which persists it to the MinIO bucket and returns the
// object metadata proving it landed.

import type {
  DocumentSourceResponse,
  StorageHealth,
  StoreDocumentRequest,
  StoreDocumentResponse,
} from '../contracts/storedDocument'
import { requestJson } from './http'

const MODALITY_PATHS = {
  typed: 'typed',
  handwritten: 'handwritten',
  multilingual: 'multilingual',
} as const

export async function storeSourceDocument(request: StoreDocumentRequest): Promise<StoreDocumentResponse> {
  const body = new FormData()
  body.append('file', request.file, request.file.name)
  body.append('patient_id', request.patient_id)
  body.append('encounter_id', request.encounter_id)
  body.append('source_language', request.source_language)

  // No Content-Type header: the browser must set the multipart boundary.
  return requestJson<StoreDocumentResponse>(
    `/v1/step1/documents/${MODALITY_PATHS[request.modality]}`,
    { method: 'POST', body },
  )
}

export async function getStoredDocumentSource(documentId: string): Promise<DocumentSourceResponse> {
  return requestJson<DocumentSourceResponse>(`/v1/step1/documents/${documentId}/source`)
}

export async function getStorageHealth(): Promise<StorageHealth> {
  return requestJson<StorageHealth>('/health', { atServerRoot: true })
}
