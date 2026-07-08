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
