import svelte from "@astrojs/svelte";
import { defineConfig } from "astro/config";
import { fileURLToPath } from "node:url";

// "/<repo>" for GitHub's project-pages subpath, set by the deploy workflow.
const base = process.env.BASE_PATH ?? "";

export default defineConfig({
  site: "https://ocha-dap.github.io",
  base,
  integrations: [svelte()],
  vite: {
    resolve: {
      alias: { $lib: fileURLToPath(new URL("./src/lib", import.meta.url)) },
    },
  },
});
