import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The API base defaults to same-origin "/api" (see src/services/api.ts). In
// development we proxy that to the Flask backend so no hardcoded host is needed.
const BACKEND = process.env.VITE_DEV_BACKEND || 'http://localhost:5000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: BACKEND,
        changeOrigin: true
      }
    }
  }
})
