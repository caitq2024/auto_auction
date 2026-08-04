import { resolve } from 'node:path'

import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  base: './',
  build: {
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html'),
        harness: resolve(__dirname, 'harness.html'),
      },
    },
  },
  server: {
    proxy: { '/api': { target: 'https://localhost:8688', secure: false } },
  },
  preview: {
    proxy: { '/api': { target: 'https://localhost:8688', secure: false } },
  },
})
