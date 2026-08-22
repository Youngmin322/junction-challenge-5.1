import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vite';

const demoRoot = fileURLToPath(new URL('.', import.meta.url));
const repositoryRoot = fileURLToPath(new URL('..', import.meta.url));

export default defineConfig({
  root: demoRoot,
  server: { fs: { allow: [repositoryRoot] } },
  build: {
    outDir: fileURLToPath(new URL('../dist/demo', import.meta.url)),
    emptyOutDir: true,
  },
});
