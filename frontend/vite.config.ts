import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The backend has no CORS configuration, so the browser talks to Vite and Vite
// forwards /v1 to the FastAPI server. Nothing in the backend is changed.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/v1": { target: "http://localhost:8000", changeOrigin: true },
      "/health": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
