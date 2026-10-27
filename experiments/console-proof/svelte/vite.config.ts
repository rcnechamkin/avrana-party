// The Svelte 5 console (AVR-762 experiment): a static, offline build under /party/x/svelte/.
// The real web/party modules and the experiment's shared rules are bundled in from their files;
// the Concept K stylesheet stays the shared /party/styles.css (not bundled), as for vanilla.
import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { fileURLToPath } from 'node:url';

const at = (p: string) => fileURLToPath(new URL(p, import.meta.url));
export default defineConfig({
  root: at('.'),
  base: '/party/x/svelte/',
  plugins: [svelte()],
  resolve: {
    alias: [
      { find: /^\/party\/x\/shared\//, replacement: at('../web/party-x/shared/') },
      { find: /^\/party\/lib\//, replacement: at('../../../web/party/lib/') },
      { find: /^\/party\/bridge\//, replacement: at('../../../web/party/bridge/') },
    ],
  },
  build: { outDir: at('dist'), emptyOutDir: true, target: 'es2022', modulePreload: { polyfill: false }, reportCompressedSize: true },
});
