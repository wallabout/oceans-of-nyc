import { defineCollection, z } from 'astro:content';
import { glob } from 'astro/loaders';

export const collections = {
  blog: defineCollection({
    loader: glob({ pattern: '**/*.md', base: './src/content/blog' }),
    schema: z.object({
      title: z.string(),
      date: z.coerce.date(),
      description: z.string(),
      author: z.string().default('Oceans of NYC'),
      draft: z.boolean().default(false),
    }),
  }),
};
