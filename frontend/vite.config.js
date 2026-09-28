import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Dev-server exposure: bind to loopback by default. The /api proxy below reaches
// Flask from 127.0.0.1, which the backend trusts without a token, so listening on
// every interface would hand the whole API to anyone on the network. Set
// FRONTEND_HOST (e.g. 0.0.0.0) only on a network you trust; the backend then sees
// the original client address in X-Forwarded-For and applies APP_API_TOKEN.
// The default is the IPv4 loopback literal, not 'localhost': Node resolves
// 'localhost' to ::1 first on macOS, so Vite would listen on ::1 only and refuse
// http://127.0.0.1:3000. Browsers and curl fall back from ::1 to 127.0.0.1, so
// http://localhost:3000 keeps working too.
const host = process.env.FRONTEND_HOST || '127.0.0.1'

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
