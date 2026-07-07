import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Proxy en desarrollo: el backend corre en :8000. En producción (Replit)
// FastAPI sirve directamente frontend/dist ⇒ mismo origen, sin CORS.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
