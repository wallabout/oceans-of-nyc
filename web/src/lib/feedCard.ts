/**
 * The sighting card used on /feed, /tagged and /random.
 *
 * One builder so every page renders a photo the same way — same image sizing,
 * same badge and Ocean Points treatment, same tag bar. Styles live in
 * global.css under "Feed cards"; a page that uses this gets them for free.
 */

import { escapeHTML } from './tags';

export interface FeedCardOptions {
  /** Badge definitions by name, from oceans.json. Badges are skipped without it. */
  badgeDefs?: Map<string, { display_name: string; description: string; emoji: string }>;
  /** Render the "Tag photo" button and the chip container. Defaults to true. */
  tagging?: boolean;
  /** Label for the tag button — /tagged uses "Add a tag". */
  tagButtonLabel?: string;
  /**
   * Drop the invisible link that makes the whole card clickable. /random keeps
   * interactive controls inside the card, where that overlay would both swallow
   * clicks and navigate away mid-tagging.
   */
  cardLink?: boolean;
}

/**
 * Build one card. The chip container is left empty: pages fill
 * `[data-tags-for="<id>"]` once tags.json lands, so a slow tag fetch never
 * delays the photos.
 */
export function buildFeedCard(sighting: any, vehicle: any, options: FeedCardOptions = {}): HTMLElement {
  const { badgeDefs, tagging = true, tagButtonLabel = '🏷️ Tag photo', cardLink = true } = options;

  const card = document.createElement('div');
  const isFirst = sighting.global_unique_sighting_index != null;
  card.className = 'feed-card'
    + (isFirst ? ' feed-card-first' : '')
    + (cardLink ? '' : ' feed-card--no-overlay');

  const platesText = vehicle.license_plates.map((p: { license_plate: string }) => p.license_plate).join(', ');
  const date = new Date(sighting.timestamp);
  const formattedDate = date.toLocaleDateString('en-US', { month: 'numeric', day: 'numeric', year: 'numeric', timeZone: 'America/New_York' });
  const formattedTime = date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true, timeZone: 'America/New_York' });

  const badgesHTML = badgeDefs && sighting.badges?.length > 0
    ? `<div class="feed-badges">${sighting.badges.map((b: { name: string }) => {
        const def = badgeDefs.get(b.name);
        return def ? `<span class="feed-badge" title="${escapeHTML(def.description)}">${def.emoji} ${escapeHTML(def.display_name)}</span>` : '';
      }).join('')}</div>`
    : '';

  const opOverlay = isFirst && sighting.ocean_points != null
    ? `<a href="/p/ocean-points" class="feed-op-badge feed-op-badge-overlay"><span class="feed-op-badge-num">${sighting.ocean_points.toFixed(1)}</span> ◎p</a>`
    : '';
  const imageInner = sighting.image
    ? `<img src="${escapeHTML(sighting.image)}" alt="Vehicle ${escapeHTML(platesText)}" class="feed-card-image" loading="lazy">`
    : `<div class="feed-card-placeholder"><img src="/fisker_ocean_placeholder.svg" alt="No photo"></div>`;
  const imageHTML = `<div class="feed-card-image-wrap">${imageInner}${opOverlay}</div>`;

  const plateLink = `<a class="feed-card-main-link" href="/ocean/${encodeURIComponent(vehicle.vin)}">${escapeHTML(platesText)}</a>`;
  const contributorPart = sighting.contributor
    ? ` from ${sighting.contributor_id != null
        ? `<a class="feed-card-contributor-link" href="/contributor/${sighting.contributor_id}">${escapeHTML(sighting.contributor)}</a>`
        : escapeHTML(sighting.contributor)}`
    : '';

  const metaParts = [
    isFirst ? `<span class="feed-first-badge">Ocean #${sighting.global_unique_sighting_index}</span>` : '',
    sighting.global_sighting_index != null ? `<span>Sighting #${sighting.global_sighting_index}</span>` : '',
    sighting.borough ? `<span>in ${escapeHTML(sighting.borough)}</span>` : '',
    `<span>at ${formattedDate} ${formattedTime}</span>`,
  ].filter(Boolean).join('');

  const tagBar = tagging && sighting.id != null
    ? `<div class="feed-card-tagbar"><div class="feed-card-tags" data-tags-for="${sighting.id}"></div><button type="button" class="tag-button" data-tag-sighting="${sighting.id}">${tagButtonLabel}</button></div>`
    : '';

  card.innerHTML = `${imageHTML}<div class="feed-card-body"><div class="feed-card-plate">${plateLink}${contributorPart}</div><div class="feed-card-meta">${metaParts}</div>${badgesHTML}${tagBar}</div>`;
  return card;
}
