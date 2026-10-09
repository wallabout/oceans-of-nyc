// Build-time access to oceans.json. Several pages render from it at build
// (the homepage intro, every /ocean and /contributor page), so it is fetched
// once per build and shared rather than downloaded by each getStaticPaths.
//
// `npm run dev` — or a build with OCEANS_DATA=local — reads public/oceans.json
// instead of the CDN, so the site can be built offline from a local export.
let cached: Promise<any> | undefined;

export function loadOceans(): Promise<any> {
  cached ??= (async () => {
    if (import.meta.env.DEV || process.env.OCEANS_DATA === 'local') {
      const { readFile } = await import('node:fs/promises');
      const { resolve } = await import('node:path');
      return JSON.parse(await readFile(resolve('public/oceans.json'), 'utf-8'));
    }
    const res = await fetch('https://cdn.oceansofnyc.com/web/oceans.json', { cache: 'no-store' });
    return res.json();
  })();
  return cached;
}
