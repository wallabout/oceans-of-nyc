import { defineCollection, z } from 'astro:content';
import { glob } from 'astro/loaders';

export const collections = {
  pages: defineCollection({
    loader: glob({ pattern: '**/*.md', base: './src/content/pages' }),
    schema: z.object({
      title: z.string(),
      posted: z.coerce.date().optional(),
      updated: z.coerce.date().optional(),
      description: z.string(),
      author: z.string().default('Oceans of NYC'),
      category: z.string(),
      draft: z.boolean().default(false),
    }).refine(d => d.posted || d.updated, {
      message: "At least one of 'posted' or 'updated' must be set",
    }),
  }),
};
