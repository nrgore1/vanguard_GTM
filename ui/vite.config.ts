import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// `npm run dev` proxies API calls to `vanguard serve` on :8080
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, proxy: { "/api": "http://localhost:8080", "/health": "http://localhost:8080" } },
  build: { chunkSizeWarningLimit: 1200 },
});
