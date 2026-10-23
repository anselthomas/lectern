import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // amazon-cognito-identity-js expects Node's `global`.
  define: { global: "globalThis" },
  server: {
    proxy: { "/api": { target: "https://d1c6wdw7xblc4l.cloudfront.net", changeOrigin: true } },
  },
  build: { sourcemap: false, chunkSizeWarningLimit: 800 },
});
