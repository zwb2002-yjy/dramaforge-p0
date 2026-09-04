/// <reference types="vitest/config" />
import path from "node:path";
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { compression } from "vite-plugin-compression2";
import { defineConfig } from "vite";

const rootDir = path.dirname(fileURLToPath(import.meta.url));
const apiTarget = process.env.DRAMAFORGE_API_URL ?? "http://127.0.0.1:8080";

export default defineConfig({
  cacheDir: "./tmp/vite-cache",
  plugins: [
    react(),
    // Precompress assets for the formal Nginx gateway (`gzip_static`). The
    // gateway image serves only `.gz`, so gzip is the single explicit
    // algorithm — do not add brotli without a Nginx module change.
    compression({ algorithms: ["gzip"] }),
  ],
  resolve: {
    alias: {
      "@": path.resolve(rootDir, "src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // The local development gateway is published on port 8080.
      "/api": apiTarget,
      "/health": apiTarget,
    },
  },
  build: {
    rollupOptions: {
      output: {
        // Function form keeps each vendor family in its own cacheable chunk
        // (the object form merged react into the tanstack chunk).
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          if (id.includes("react-dom")) return "vendor-react";
          if (id.includes("react-router")) return "vendor-tanstack";
          if (id.includes("@tanstack")) return "vendor-tanstack";
          if (id.includes("zustand")) return "vendor-zustand";
          if (id.includes("lucide-react")) return "vendor-lucide";
          if (id.includes("react")) return "vendor-react";
          return undefined;
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/unit/setup.ts"],
    include: ["tests/unit/**/*.{test,spec}.{ts,tsx}"],
  },
});
