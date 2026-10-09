import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

export default defineConfig({
  // Canonical origin: used for <link rel="canonical">, og:url and the sitemap.
  site: 'https://oceansofnyc.com',
  output: 'static',
  integrations: [
    sitemap({
      // Internal tools and the photo-tagging game aren't landing pages.
      filter: (page) => !/\/(admin-stats|random|about)\/$/.test(new URL(page).pathname),
    }),
  ],
  build: {
    format: 'directory',
  },
  redirects: {
    // The old placeholder About page; the real explainer lives in the posts.
    '/about': '/p/what-is-oceans-of-nyc',
  },
  vite: {
    build: {
      // Vite 8 minifies CSS with Lightning CSS, whose default target
      // ('baseline-widely-available') rewrites `@media (max-width: 640px)` into
      // the Media Queries 4 range syntax `@media (width <= 640px)`. That syntax
      // needs Safari 16.4+, and a browser that doesn't understand it drops the
      // whole block — so every mobile breakpoint would silently vanish rather
      // than degrade. Our own CSS only reaches for Safari 15.4 features
      // (accent-color, aspect-ratio), which fail gracefully, so pin the floor
      // there and keep the old syntax. Costs ~75 bytes of CSS.
      cssTarget: ['chrome107', 'edge107', 'firefox104', 'safari15.4'],
    },
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
