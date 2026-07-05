import babel from "@rolldown/plugin-babel";
import react, { reactCompilerPreset } from "@vitejs/plugin-react";
import path from "node:path";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  // 读取项目根目录的 .env 文件（与 backend/knowgraph/utils/environments.py 保持一致）
  const envDir = path.resolve(__dirname, "..");
  const env = loadEnv(mode, envDir, "");

  const apiHost = env.FASTAPI_HOST || "127.0.0.1";
  const apiPort = env.FASTAPI_PORT || "40001";

  return {
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
