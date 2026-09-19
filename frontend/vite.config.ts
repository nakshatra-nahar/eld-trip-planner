import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
  // maplibre's worker imports a shared ES chunk, so workers must be bundled as ES modules.
  worker: { format: 'es' },
  build: {
    // maplibre-gl alone is ~1 MB minified (280 kB gzip) and already lives in its own chunk.
    chunkSizeWarningLimit: 1100,
  },
})
