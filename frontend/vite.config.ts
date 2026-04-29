import path from 'path'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    proxy: {
      '/api': {
        target: process.env.NOVA_FRONTEND_PROXY_TARGET || 'http://127.0.0.1:8765',
        changeOrigin: true,
      },
      '/health': {
        target: process.env.NOVA_FRONTEND_PROXY_TARGET || 'http://127.0.0.1:8765',
        changeOrigin: true,
      },
    },
  },
})
