import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import process from "node:process";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const backendUrl = env.VITE_BACKEND_URL || "http://127.0.0.1:23333";
  const frontendHost = env.VITE_DEV_HOST || "127.0.0.1";
  const frontendPort = Number(env.VITE_DEV_PORT || "5173");

  return {
    plugins: [react()],
    server: {
      host: frontendHost,
      port: frontendPort,
      proxy: {
        "/api": backendUrl,
      },
    },
  };
});
