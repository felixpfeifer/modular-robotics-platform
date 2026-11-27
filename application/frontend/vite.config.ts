import { defineConfig } from "vite";

const backend = {
  target: process.env.MRP_PROXY_TARGET || "http://127.0.0.1:8088",
  changeOrigin: false,
};

export default defineConfig({
  build: {
    rollupOptions: {
      onwarn(warning, defaultHandler) {
        if (
          warning.code === "MODULE_LEVEL_DIRECTIVE" &&
          warning.id?.includes("/node_modules/@mui/") &&
          warning.message.includes('"use client"')
        ) {
          return;
        }
        defaultHandler(warning);
      },
    },
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": { ...backend, ws: true },
      "/docs": backend,
      "/redoc": backend,
      "/health": backend,
      "/openapi.json": backend,
    },
  },
});
