import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  base: './',
  server: {
    proxy: { '/api': { target: 'https://localhost:8688', secure: false } },
  },
  preview: {
    proxy: { '/api': { target: 'https://localhost:8688', secure: false } },
  },
})
