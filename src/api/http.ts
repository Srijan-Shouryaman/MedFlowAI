// Minimal HTTP helper for the one backend that exists today.
//
// Every other module in this folder is still a local mock. Only the document
// storage path talks to a real server, so this stays deliberately small rather
// than becoming a client for endpoints that have not been designed yet.

const DEFAULT_BASE_URL = '/api'

export function apiBaseUrl(): string {
  const configured = import.meta.env?.VITE_API_BASE_URL as string | undefined
  return (configured ?? DEFAULT_BASE_URL).replace(/\/+$/, '')
}

export class ApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message)
    this.name = 'ApiError'
  }
}

// FastAPI reports failures as `detail`, which is either a string or an array of
// validation objects. Anything else falls back to the status text so the UI
// never renders "[object Object]".
async function errorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json()
    const detail = body?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0]
      if (typeof first?.msg === 'string') return first.msg
    }
  } catch {
    // Non-JSON body; fall through to the status text.
  }
  return response.statusText || `Request failed with status ${response.status}`
}

export interface RequestOptions extends RequestInit {
  // Health lives at the server root rather than under the /api prefix, so it
  // needs to opt out of the base URL.
  atServerRoot?: boolean
}

export async function requestJson<T>(path: string, options?: RequestOptions): Promise<T> {
  const { atServerRoot = false, ...init } = options ?? {}
  const url = atServerRoot ? path : `${apiBaseUrl()}${path}`
  let response: Response
  try {
    response = await fetch(url, init)
  } catch {
    // fetch only rejects on a transport failure, never on an HTTP error status.
    throw new ApiError(0, 'The backend is unreachable. Is it running on port 8000?')
  }
  if (!response.ok) {
    throw new ApiError(response.status, await errorMessage(response))
  }
  return (await response.json()) as T
}
