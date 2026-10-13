import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  base: '/',
  build: { outDir: '../ashare_monitor/web', emptyOutDir: true, sourcemap: false },
  server: {
    host: '127.0.0.1',
    proxy: { '/api': { target: 'http://127.0.0.1:18766', changeOrigin: true,
      configure(proxy) { proxy.on('proxyReq', (request) => { request.removeHeader('origin') }) } } },
  },
  test: { environment: 'jsdom', include: ['src/tests/**/*.test.ts'], clearMocks: true },
})
