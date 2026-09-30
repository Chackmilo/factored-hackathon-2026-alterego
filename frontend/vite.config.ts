import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The API is served by FastAPI on port 8000. In dev, Vite proxies /api there so the
// app can use relative URLs; in production FastAPI serves frontend/dist itself.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
  },
})
