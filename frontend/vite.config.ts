import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// Dev server proxies /api to the FastAPI backend, so the SPA and the API share
// the same origin (session cookies work without CORS setup).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true, // reachable from a phone on the same network
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})