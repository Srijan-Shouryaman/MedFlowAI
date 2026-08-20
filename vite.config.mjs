import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The dev server proxies to the backend so the browser sees one origin and no
// CORS preflight is involved. The backend also sets CORS headers, for anyone
// pointing VITE_API_BASE_URL straight at http://localhost:8000.
const backendTarget = process.env.VITE_BACKEND_TARGET ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': { target: backendTarget, changeOrigin: true },
      '/health': { target: backendTarget, changeOrigin: true },
    },
  },
})
