import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Build assets with a RELATIVE base so a single image works under any path.
// The actual mount path is decided at runtime: the backend injects
// <base href="{ROOT_PATH}/"> and window.__APP_BASE__ into index.html, so
// relative asset URLs (./assets/...) resolve correctly at "/" or "/polymarket/".
export default defineConfig({
  base: './',
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
