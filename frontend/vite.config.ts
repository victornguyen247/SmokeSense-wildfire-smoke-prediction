import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    // The map chunk is MapLibre itself (~1 MB, ~275 kB gzipped) and is lazy-loaded
    // after the page shell; the app's own entry chunk stays well under 500 kB.
    chunkSizeWarningLimit: 1100,
  },
})
