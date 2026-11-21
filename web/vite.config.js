import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: proxies API calls to the FastAPI service on :8000.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/audit": "http://127.0.0.1:8000", "/health": "http://127.0.0.1:8000", "/corpora": "http://127.0.0.1:8000" },
  },
});
