# Oceans of NYC — Web

Static site built with [Astro](https://astro.build), tracking every Fisker Ocean vehicle operating in NYC.

## Local development

```bash
cd web
npm install       # first time only
npm run dev       # dev server at http://localhost:4321 with hot reload
```

> Vehicle images are served from the CDN and won't load locally unless you're online. Placeholders display for vehicles without sightings — this is normal.

## Build & preview

```bash
npm run build     # outputs to web/dist/
npm run preview   # serve the built dist/ locally for a production preview
```

## Deployment

Point your server or CDN to the `dist/` directory produced by `npm run build`.

## Adding a blog post

Create a Markdown file in `src/content/blog/`:

```
src/content/blog/my-post-title.md
```

Required frontmatter:

```md
---
title: "Post Title"
date: 2026-05-01
description: "One-sentence summary shown on the blog listing."
author: "Your Name"        # optional, defaults to "Oceans of NYC"
draft: false               # set true to hide from production build
---

Post content here...
```

The post will be available at `/blog/my-post-title`.

## Project structure

```
web/
├── src/
│   ├── components/
│   │   └── Nav.astro              # Shared navigation bar
│   ├── content/
│   │   └── blog/                  # Markdown blog posts
│   ├── layouts/
│   │   ├── Layout.astro           # Base layout (nav, global CSS, shared script)
│   │   └── BlogPost.astro         # Blog post layout with prose styles
│   ├── lib/
│   │   └── tags.ts                # Photo tagging client (picker, chips, submit)
│   ├── pages/
│   │   ├── index.astro            # Grid view  →  /
│   │   ├── feed.astro             # Feed view  →  /feed
│   │   ├── stats.astro            # Stats      →  /stats
│   │   ├── badges.astro           # Badges  →  /badges
│   │   ├── tagged.astro           # Tagged photos + tag filter  →  /tagged
│   │   ├── random.astro           # Tag a random photo  →  /random
│   │   ├── submit.astro           # Submit form  →  /submit
│   │   ├── about.astro            # About  →  /about
│   │   └── blog/
│   │       ├── index.astro        # Blog listing  →  /blog
│   │       └── [...slug].astro    # Individual posts  →  /blog/slug
│   └── styles/
│       └── global.css             # Shared nav, modal, filter-bar styles
├── public/
│   ├── favico/
│   ├── fisker_ocean_placeholder.svg
│   └── oceans_of_nyc_logo.png
├── astro.config.mjs
└── package.json
```

## Data

All vehicle and sighting data is fetched at runtime from the CDN:

```
https://cdn.oceansofnyc.com/web/oceans.json
https://cdn.oceansofnyc.com/web/tags.json          # community photo tags
https://cdn.oceansofnyc.com/web/daily_sightings.json
```

Sighting submissions POST to a Modal webhook endpoint. Neither the data file nor images are part of this repository.

## Photo tags

Visitors can tag any sighting photo ("rare color: coffee", "great photography",
"report") from the feed, from `/random`, or from `/tagged`. Tags are anonymous:
the browser keeps a random id in `localStorage` and the API stores it alongside
a salted hash of the request IP, which is enough to drop repeat nominations from
the same person.

Nominations are fire-and-forget — the UI updates immediately and never waits on
the network. Counts are published separately from `oceans.json` (they change far
more often, and the payload is tiny) and refreshed after each new tag, with a
15-minute scheduled backstop.

For local development, generate both files into `public/`:

```bash
cd ..                            # repo root
uv run python web/generate_data.py     # writes web/oceans.json + web/tags.json
cp web/oceans.json web/tags.json web/public/
```
