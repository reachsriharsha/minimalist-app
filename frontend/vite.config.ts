import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  // Load env files (.env, .env.local, etc.) from this directory so the dev
  // proxy target can be configured via VITE_API_BASE_URL without exporting it
  // in the shell. loadEnv() does not require the VITE_ prefix restriction for
  // config-time use, but we keep the one-variable contract described in the
  // design spec.
  const env = loadEnv(mode, process.cwd(), '');
  const apiTarget = env.VITE_API_BASE_URL ?? 'http://localhost:8000';

  return {
    plugins: [react()],
    server: {
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
        },
      },
    },
    preview: {
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
        },
      },
    },
  };
});
