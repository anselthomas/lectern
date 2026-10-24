import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  // For `npm run dev`, LECTERN_API_URL (in .env.local) points /api at a running deployment.
  const api = loadEnv(mode, process.cwd(), "").LECTERN_API_URL;
  return {
    plugins: [react()],
    // amazon-cognito-identity-js expects Node's `global`.
    define: { global: "globalThis" },
    server: api ? { proxy: { "/api": { target: api, changeOrigin: true } } } : {},
    build: { sourcemap: false, chunkSizeWarningLimit: 800 },
  };
});
