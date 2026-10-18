import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The backend (uvicorn app.main:app) listens on 8000. In dev, /api and /health are proxied to it,
// so the browser only talks to the Vite server and no CORS setup is needed.
const BACKEND = process.env.VITE_BACKEND_URL || "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: BACKEND, changeOrigin: true },
      "/health": { target: BACKEND, changeOrigin: true }
    }
  }
});
