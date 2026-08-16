import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8300',
      // L'interface Chainlit montée sur /chat. `ws` est indispensable :
      // Chainlit fait transiter les messages par websocket, pas par HTTP.
      '/chat': { target: 'http://127.0.0.1:8300', ws: true },
    },
  },
})
