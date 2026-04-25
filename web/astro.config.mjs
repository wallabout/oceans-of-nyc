import { defineConfig } from 'astro/config';

export default defineConfig({
  output: 'static',
  build: {
    format: 'directory',
  },
  vite: {
    server: {
      proxy: {
        // Proxies /cdn/* → https://cdn.oceansofnyc.com/* during `npm run dev`.
        // Requests go server-side so CORS doesn't apply.
        // In production the JS fetches the CDN URL directly.
        '/cdn': {
          target: 'https://cdn.oceansofnyc.com',
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/cdn/, ''),
        },
      },
    },
  },
});
