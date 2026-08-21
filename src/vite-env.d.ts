/// <reference types="vite/client" />

interface ImportMetaEnv {
  // Override to talk to the backend directly instead of through the dev proxy,
  // e.g. VITE_API_BASE_URL=http://localhost:8000/api
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
