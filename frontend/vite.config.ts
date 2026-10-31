import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Like the web image's nginx: with a token set, the dev proxy adds it to every /api/ request on the
// server side, so the browser never sees it. Not VITE_-prefixed, so it never reaches the bundle.
const devProxyToken = process.env.OPS_SIGNALS_DEV_PROXY_API_TOKEN;

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules')) {
            if (id.includes('@mui/')) return 'mui';
            if (id.includes('@grafana/')) return 'grafana';
            if (id.includes('@tanstack/react-query')) return 'react-query';
            if (id.includes('recharts')) return 'recharts';
            return 'vendor';
          }
        },
      },
    },
    chunkSizeWarningLimit: 900,
  },
  server: {
    port: Number(process.env.VITE_FRONTEND_PORT ?? 5174),
    proxy: {
      '/api': {
        target: `http://localhost:${process.env.VITE_API_PORT ?? '8000'}`,
        changeOrigin: true,
        ...(devProxyToken ? { headers: { Authorization: `Bearer ${devProxyToken}` } } : {}),
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    coverage: {
      provider: 'v8',
      include: ['src/**/*.{ts,tsx}'],
      exclude: ['src/**/*.test.{ts,tsx}', 'src/**/*.d.ts', 'src/test/**'],
    },
  },
});
