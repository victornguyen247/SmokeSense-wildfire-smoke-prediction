import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'

const CHUNK_BUDGET_KB = 500

/**
 * Warn when one of our chunks grows past CHUNK_BUDGET_KB. Exempt: the chunk holding
 * MapLibre (~1 MB on its own, lazy-loaded, size outside our control) and the mock-mode
 * chunk (MSW + fixtures, only built with VITE_USE_MOCKS=true). A plain
 * chunkSizeWarningLimit would have to be raised for every chunk to quiet MapLibre.
 */
function chunkBudget(): Plugin {
  return {
    name: 'smokesense-chunk-budget',
    apply: 'build',
    generateBundle(_options, bundle) {
      for (const chunk of Object.values(bundle)) {
        if (chunk.type !== 'chunk') continue
        const ids = chunk.moduleIds
        if (ids.some((id) => id.includes('/node_modules/maplibre-gl/') || id.includes('/src/mocks/'))) continue
        const kb = new TextEncoder().encode(chunk.code).length / 1000
        if (kb > CHUNK_BUDGET_KB) {
          this.warn(`${chunk.fileName} is ${Math.round(kb)} kB, over the ${CHUNK_BUDGET_KB} kB chunk budget.`)
        }
      }
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), chunkBudget()],
  build: {
    // Vite's own check would flag the exempt chunks above; chunkBudget() replaces it.
    chunkSizeWarningLimit: Number.POSITIVE_INFINITY,
  },
})
