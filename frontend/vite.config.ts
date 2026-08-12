import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    // Only used by `npm run dev`. In the container nginx serves the build and
    // proxies /api, so there is no CORS and no second port to explain.
    proxy: { "/api": "http://localhost:8000" },
  },
});
