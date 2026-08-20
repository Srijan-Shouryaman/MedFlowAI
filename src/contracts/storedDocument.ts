import type { InputModality, ISODate, ProcessingStatus } from './common'

// Returned by the backend after the uploaded bytes land in the bucket. It
// carries object metadata only -- no clinical content -- so it is safe to
// render in the UI as proof the upload was persisted.
export interface StoredObjectSummary {
  bucket: string
  key: string
  storage_uri: string
  content_type: string
  size_bytes: number
  checksum_sha256: string
  version_id: string | null
  backend: string
}

export interface StoreDocumentRequest {
  file: File
  patient_id: string
  encounter_id: string
  modality: InputModality
  source_language: string
}

export interface StoreDocumentResponse {
  document_id: string
  job_id: string
  processing_status: ProcessingStatus
  stored: StoredObjectSummary
}

export interface DocumentSourceResponse {
  document_id: string
  download_url: string
  expires_at: ISODate
  content_type: string
  size_bytes: number
}

export interface StorageHealth {
  status: 'ok'
  storage_backend: string
  bucket: string
  // False whenever the backend is on in-memory storage, which is otherwise
  // indistinguishable from a working system on this side of the wire.
  persistent: boolean
}
