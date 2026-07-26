import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

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
    port: Number(process.env.VITE_FRONTEND_PORT ?? 5173),
    proxy: {
      '/api': {
        target: `http://localhost:${process.env.VITE_API_PORT ?? '8000'}`,
        changeOrigin: true,
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
  },
});
