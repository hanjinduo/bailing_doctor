import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// 构建产物直接写入后端 static 目录，FastAPI 首页返回 static/index.html
export default defineConfig({
  plugins: [vue()],
  base: '/',
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) }
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true }
    }
  },
  build: {
    outDir: '../static',
    emptyOutDir: true,
    chunkSizeWarningLimit: 1500
  }
})
