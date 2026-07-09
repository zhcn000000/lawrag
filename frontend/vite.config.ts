import path from "node:path";
import babel from "@rolldown/plugin-babel";
import react, { reactCompilerPreset } from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const envDir = path.resolve(__dirname, "..");
  const env = loadEnv(mode, envDir, "");

  const apiHost = env.FASTAPI_HOST || "127.0.0.1";
  const apiPort = env.FASTAPI_PORT || "40001";

  return {
    base: "/webui/",
    plugins: [
      react({
        jsxImportSource: "@emotion/react",
      }),

      babel({
        plugins: ["@emotion/babel-plugin"],
        presets: [reactCompilerPreset()],
      }),
    ],
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "src"),
      },
    },
    server: {
      proxy: {
        "/api": {
          target: `http://${apiHost}:${apiPort}`,
          changeOrigin: true,
        },
      },
    },
  };
});
