import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Dev-server exposure: bind to loopback by default. The /api proxy below reaches
// Flask from 127.0.0.1, which the backend trusts without a token, so listening on
// every interface would hand the whole API to anyone on the network. Set
// FRONTEND_HOST (e.g. 0.0.0.0) only on a network you trust; the backend then sees
// the original client address in X-Forwarded-For and applies APP_API_TOKEN.
const host = process.env.FRONTEND_HOST || 'localhost'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    host,
    port: 3000,
    strictPort: true,
    open: true,
    proxy: {
      '/api': {
        target: 'http://localhost:5001',
        changeOrigin: true,
        secure: false,
        // Forward the real client address so the backend auth gate can tell a LAN
        // browser from a local one.
        xfwd: true
      }
    }
  }
})
