import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // Forward /api/* requests to the FastAPI backend
      '/api': {
        target: 'http://backend:8000',
        changeOrigin: true,
      },
      // Forward all WebSocket connections (progress + conversation)
      '/ws': {
        target: 'ws://backend:8000',
        ws: true,
        changeOrigin: true,
      },
    },
  },
})
