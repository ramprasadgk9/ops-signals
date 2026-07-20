import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'node:path';

export default defineConfig({
  plugins: [
    react({
      jsxRuntime: 'classic',
    }),
    {
      name: 'grafana-systemjs-react-interop',
      generateBundle(_options, bundle) {
        for (const output of Object.values(bundle)) {
          if (output.type !== 'chunk') continue;

          output.code = output.code.replace(
            /([A-Za-z_$][\w$]*)=([A-Za-z_$][\w$]*)\.default,([A-Za-z_$][\w$]*)=\2/g,
            '$1=$2.default??$2,$3=$2'
          );
        }
      },
    },
  ],
  define: {
    'process.env.NODE_ENV': JSON.stringify('production'),
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    lib: {
      entry: resolve(__dirname, 'src/module.ts'),
      formats: ['system'],
      fileName: () => 'module.js',
    },
    rollupOptions: {
      external: ['react', 'react-dom', '@grafana/data', '@grafana/runtime', '@grafana/ui'],
      output: {
        interop: 'compat',
      },
    },
  },
});
