import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [
    react(),
    {
      name: 'admin-root-rewrite',
      configureServer(server) {
        server.middlewares.use((req, _res, next) => {
          if (req.url === '/') {
            req.url = '/admin.html';
          }
          next();
        });
      },
    },
  ],
  root: '.',
  build: {
    rollupOptions: {
      input: 'admin.html',
    },
    outDir: 'dist-admin',
  },
  server: {
    port: Number(process.env.VITE_ADMIN_PORT ?? 5173),
    proxy: {
      '/api': {
        target: `http://localhost:${process.env.VITE_API_PORT ?? '8000'}`,
        changeOrigin: true,
      },
    },
  },
});
