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

const HOUR_MS = 3600 * 1000;
const DAY_MS = 24 * HOUR_MS;

function plural(n: number, unit: string): string {
  return n === 1 ? `${n} ${unit}` : `${n} ${unit}s`;
}

/**
 * Describe an elapsed time in the largest unit that still reads naturally:
 * "5 hours", "12 days", "4 months", "2 years". Mirrors format_duration() in
 * utils/sighting_confirmation.py so the feed and SMS replies agree.
 * Pass hours=false for date-only sources (TLC report dates).
 */
export function formatDuration(ms: number, hours = true): string {
  ms = Math.max(ms, 0);
  if (hours && ms < HOUR_MS) return 'less than an hour';
  if (hours && ms < 2 * DAY_MS) return plural(Math.floor(ms / HOUR_MS), 'hour');
  const days = Math.floor(ms / DAY_MS);
  if (days < 1) return 'less than a day';
  if (days < 60) return plural(days, 'day');
  if (days < 730) return plural(Math.round(days / 30.44), 'month');
  return plural(Math.round(days / 365.25), 'year');
}

function ordinal(n: number): string {
  const mod100 = n % 100;
  const suffix = mod100 >= 11 && mod100 <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' } as Record<number, string>)[n % 10] || 'th';
  return `${n}${suffix}`;
}

/** Earliest TLC first-report date across a vehicle's plates — when it joined the fleet. */
export function getTlcDebutDate(vehicle: any): Date | null {
  let earliest: string | null = null;
  for (const plate of vehicle.license_plates || []) {
    const m = String(plate.first_reported_on || '').match(/^\d{4}-\d{2}-\d{2}/);
    if (m && (!earliest || m[0] < earliest)) earliest = m[0];
  }
  return earliest ? new Date(earliest + 'T12:00:00') : null;
}

/**
 * The vehicle's story as of this sighting: how many times it's been seen, how
 * long before this someone first spotted it, and how long it had been in the
 * TLC fleet. Times are relative to the sighting, not to now, so an old card
 * still says how close its spotter came to a first sighting.
 */
function vehicleHistoryHTML(sighting: any, vehicle: any): string {
  const sightings = vehicle.sightings || [];
  const n = sighting.vehicle_sighting_index;
  if (n == null || !sightings.length) return '';

  const total = sightings.length;
  const seenAt = new Date(sighting.timestamp).getTime();
  const parts: string[] = [];

  const countLabel = total === 1 ? 'Only sighting so far' : `${ordinal(n)} of ${total} sightings`;
  parts.push(`<span class="feed-history-count" title="Times this Ocean has been sighted">${countLabel}</span>`);

  if (n > 1) {
    const first = sightings.find((s: any) => s.vehicle_sighting_index === 1) || sightings[0];
    const gap = seenAt - new Date(first.timestamp).getTime();
    if (gap >= 0) parts.push(`<span>first spotted ${formatDuration(gap)} earlier</span>`);
  }

  const debut = getTlcDebutDate(vehicle);
  if (debut) {
    const onRoad = seenAt - debut.getTime();
    if (onRoad >= 0) {
      parts.push(n === 1
        ? `<span>on the road ${formatDuration(onRoad, false)} unspotted</span>`
        : `<span>joined TLC ${formatDuration(onRoad, false)} earlier</span>`);
    }
  }

  return `<div class="feed-card-history">${parts.join('<span class="feed-history-sep" aria-hidden="true">·</span>')}</div>`;
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

  card.innerHTML = `${imageHTML}<div class="feed-card-body"><div class="feed-card-plate">${plateLink}${contributorPart}</div><div class="feed-card-meta">${metaParts}</div>${vehicleHistoryHTML(sighting, vehicle)}${badgesHTML}${tagBar}</div>`;
  return card;
}
