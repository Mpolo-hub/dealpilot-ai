/// <reference types="vitest/config" />
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

// Spec 007 sections 11 and 12.7 (D1, D9): local use only, one origin for pages and API.
const HOST = "127.0.0.1";
const API = "http://127.0.0.1:8000";
const proxy = {
  "/v1": { target: API, changeOrigin: false },
  "/health": { target: API, changeOrigin: false },
};

// Content Security Policy of the built app (section 11). The dev server is left without
// it because React fast refresh injects an inline script there.
const CSP =
  "default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; " +
  "img-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; " +
  "form-action 'self'; frame-ancestors 'none'";

function buildSecurity(): Plugin {
  return {
    name: "dealpilot-build-security",
    apply: "build",
    transformIndexHtml() {
      return [{ tag: "meta", attrs: { "http-equiv": "Content-Security-Policy", content: CSP },
        injectTo: "head-prepend" }];
    },
    generateBundle() {
      // OFL-1.1 requires the license to travel with the bundled Inter font (D10).
      const license = fileURLToPath(
        new URL("./node_modules/@fontsource/inter/LICENSE", import.meta.url));
      this.emitFile({ type: "asset", fileName: "licenses/inter-OFL-1.1.txt",
        source: readFileSync(license, "utf8") });
    },
  };
}

export default defineConfig({
  plugins: [react(), buildSecurity()],
  // cors: false: Vite would otherwise add Access-Control-Allow-Origin for local origins,
  // letting another local page read the API through the proxy (spec 007 D9, spec 002).
  server: { host: HOST, port: 5173, strictPort: true, cors: false, proxy },
  preview: { host: HOST, port: 4173, strictPort: true, cors: false, proxy },
  build: {
    assetsInlineLimit: 0, // no data: URIs, so the CSP needs no exceptions
    sourcemap: false,
  },
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.{ts,tsx}"],
    setupFiles: ["tests/setup.ts"],
    restoreMocks: true,
  },
});
