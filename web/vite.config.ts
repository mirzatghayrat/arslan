import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import {defineConfig} from 'vite';

export default defineConfig(() => {
  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      // Keep symlinked paths (src/node_modules are symlinks in the clean-vite
      // staging dir); otherwise Vite dev resolves them back into the repo tree
      // and fails to load the entry module / breaks Tailwind's clean scan.
      preserveSymlinks: true,
      alias: {
        '@': path.resolve(__dirname, '.'),
      },
    },
    build: {
      // Fonts stay files (IMG1-B, v0.1.64): the main window's CSP is font-src
      // 'self' (server/main.py), and Vite would inline any font under 4 KiB as
      // a data: URL, as it did KaTeX_Size3's woff2. Other assets: the default.
      assetsInlineLimit: (file: string) => (/\.(woff2?|ttf|otf|eot)$/i.test(file) ? false : undefined),
      // Two pages: the app, and the island (0.1.51) — its own small entry so
      // the notch window loads none of the app bundle or its global CSS.
      rollupOptions: {
        input: {
          index: path.resolve(__dirname, 'index.html'),
          island: path.resolve(__dirname, 'island.html'),
        },
      },
    },
    server: {
      // Bind IPv4 explicitly: on this Node, host "localhost" resolves to ::1 only,
      // and an IPv4 browser/probe then gets connection-refused on 127.0.0.1:5173.
      host: '127.0.0.1',
      port: 5173,
      hmr: process.env.DISABLE_HMR !== 'true',
      watch: process.env.DISABLE_HMR === 'true' ? null : {},
      proxy: {
        '/api': 'http://localhost:8741',
        '/ws': { target: 'ws://localhost:8741', ws: true },
      },
    },
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./src/test/setup.ts'],
    },
  };
});
