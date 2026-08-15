import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import process from 'node:process'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "")

  return {
    plugins: [react()],
    server: {
      ...(env.VITE_DEBUG === "true" && {
        proxy: {
          "/api": {
            target: "http://localhost:8000",
            changeOrigin: true,
            secure: false
          }
        }
      })
    }
  }
})
