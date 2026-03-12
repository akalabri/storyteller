import { defineConfig } from 'vite';

export default defineConfig({
  root: '.',
  build: { outDir: 'dist' },
  server: {
    port: 5173,
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: process.env.BACKEND_URL || 'http://backend:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: (process.env.BACKEND_URL || 'http://backend:8000').replace('http://', 'ws://'),
        changeOrigin: true,
        ws: true,
      },
    },
  },
});
