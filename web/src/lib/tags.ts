/**
 * Community photo tagging — shared client helpers.
 *
 * Visitors aren't logged in. A tag is a *nomination*: we fire it at the API and
 * never wait for the response, then remember locally that this browser tagged
 * this photo so the button can show as done. The server de-duplicates repeat
 * nominations using the fingerprint below plus a hash of the request IP.
 *
 * Used by /feed, /random and /tagged.
 */

const TAG_API = 'https://wallabout--oceans-of-nyc-web-tag-webhook.modal.run/tag';

const FINGERPRINT_KEY = 'oon_tagger_id';
const MY_TAGS_KEY = 'oon_my_tags';

/** Cap on how many photos we remember tagging, oldest dropped first. */
const MY_TAGS_LIMIT = 500;

export interface TagDefinition {
  name: string;
  display_name: string;
  description: string;
  emoji: string;
  /** False for moderation tags (report) — collected, but never shown on the photo. */
  public: boolean;
}

export interface TagData {
  tag_definitions: TagDefinition[];
  /** Number of distinct photos carrying each tag. */
  tag_totals: Record<string, number>;
  /** sighting id (as string) -> tag name -> nomination count */
  sighting_tags: Record<string, Record<string, number>>;
}

/**
 * Mirrors tags/definitions.py. Used until tags.json loads (and if it 404s,
 * which it does until the first refresh publishes the file), so the tagging UI
 * is never empty. Keep in sync with the Python definitions.
 */
export const DEFAULT_TAG_DEFINITIONS: TagDefinition[] = [
  { name: 'rare_color_red', display_name: 'Rare Color: Red', description: 'One of the rare red Oceans', emoji: '🟥', public: true },
  { name: 'rare_color_coffee', display_name: 'Rare Color: Coffee', description: 'One of the rare coffee-colored Oceans', emoji: '🟫', public: true },
  { name: 'multi_ocean', display_name: 'Multi-Ocean', description: 'Two or more Oceans in a single frame', emoji: '👯', public: true },
  { name: 'great_photography', display_name: 'Great Photography', description: 'A photo that belongs in a coffee table book', emoji: '📸', public: true },
  { name: 'so_nyc', display_name: "That's So NYC", description: 'A photo that captures New York City perfectly', emoji: '🗽', public: true },
  { name: 'report', display_name: 'Report', description: "Photo is broken, or isn't of the right vehicle", emoji: '🚩', public: false },
];

export const EMPTY_TAG_DATA: TagData = {
  tag_definitions: DEFAULT_TAG_DEFINITIONS,
  tag_totals: {},
  sighting_tags: {},
};

export function escapeHTML(value: unknown): string {
  return String(value).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] as string));
}

/** Storage can throw (Safari private mode, blocked cookies) — never break the page over it. */
function readStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* ignore */
  }
}

/**
 * A random per-browser id, created once and reused. This is the primary
 * de-duplication key: tagging the same photo the same way twice is a no-op.
 */
export function getFingerprint(): string {
  const existing = readStorage(FINGERPRINT_KEY);
  if (existing) return existing;
  const generated =
    typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `f-${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
  writeStorage(FINGERPRINT_KEY, generated);
  return generated;
}

/** All tags this browser has nominated, keyed by sighting id. */
function readMyTags(): Record<string, string[]> {
  const raw = readStorage(MY_TAGS_KEY);
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

export function getMyTags(sightingId: number | string): string[] {
  return readMyTags()[String(sightingId)] || [];
}

export function hasMyTag(sightingId: number | string, tag: string): boolean {
  return getMyTags(sightingId).includes(tag);
}

function rememberMyTag(sightingId: number | string, tag: string): void {
  const all = readMyTags();
  const key = String(sightingId);
  const forSighting = all[key] || [];
  if (!forSighting.includes(tag)) forSighting.push(tag);
  all[key] = forSighting;

  const keys = Object.keys(all);
  if (keys.length > MY_TAGS_LIMIT) {
    for (const stale of keys.slice(0, keys.length - MY_TAGS_LIMIT)) delete all[stale];
  }
  writeStorage(MY_TAGS_KEY, JSON.stringify(all));
}

/**
 * Send a nomination. Deliberately not awaited anywhere: the UI updates
 * optimistically and a failed request is simply a lost vote, not an error the
 * visitor needs to see. `keepalive` lets the request survive navigation, which
 * matters on /random where the next photo loads immediately.
 */
export function submitTag(sightingId: number | string, tag: string): void {
  rememberMyTag(sightingId, tag);
  try {
    fetch(TAG_API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sighting_id: Number(sightingId), tag, fingerprint: getFingerprint() }),
      keepalive: true,
    }).catch(() => {});
  } catch {
    /* ignore */
  }
}

/** Fetch published tag counts. Resolves to empty data rather than rejecting. */
export function loadTagData(): Promise<TagData> {
  const url =
    window.location.hostname === 'localhost'
      ? '/tags.json'
      : 'https://cdn.oceansofnyc.com/web/tags.json';
  return fetch(url)
    .then((r) => (r.ok ? r.json() : EMPTY_TAG_DATA))
    .then((data: TagData) => ({
      tag_definitions: data.tag_definitions?.length ? data.tag_definitions : DEFAULT_TAG_DEFINITIONS,
      tag_totals: data.tag_totals || {},
      sighting_tags: data.sighting_tags || {},
    }))
    .catch(() => EMPTY_TAG_DATA);
}

/** Counts for one photo, merged with anything this browser just nominated. */
export function countsFor(data: TagData, sightingId: number | string): Record<string, number> {
  const stored = { ...(data.sighting_tags[String(sightingId)] || {}) };
  for (const tag of getMyTags(sightingId)) {
    if (!stored[tag]) stored[tag] = 1;
  }
  return stored;
}

/** Chips shown on a photo card for its public tags. Returns '' when there are none. */
export function renderTagChips(counts: Record<string, number>, defs: TagDefinition[]): string {
  const byName = new Map(defs.map((d) => [d.name, d]));
  const chips = Object.entries(counts)
    .filter(([name]) => byName.get(name)?.public)
    .sort((a, b) => b[1] - a[1])
    .map(([name, count]) => {
      const def = byName.get(name) as TagDefinition;
      const countLabel = count > 1 ? ` <span class="photo-tag__count">${count}</span>` : '';
      return `<a class="photo-tag" href="/tagged?tag=${encodeURIComponent(name)}" title="${escapeHTML(def.description)}">${def.emoji} ${escapeHTML(def.display_name)}${countLabel}</a>`;
    });
  return chips.length ? `<div class="photo-tags">${chips.join('')}</div>` : '';
}

/**
 * Build the tag picker panel for one photo.
 *
 * Nominations are add-only — once sent, the button locks into a "tagged" state.
 * `onTagged` lets the host page refresh its own chips optimistically.
 */
export function buildTagPicker(
  sightingId: number | string,
  defs: TagDefinition[],
  onTagged?: (tag: string) => void
): HTMLElement {
  const panel = document.createElement('div');
  panel.className = 'tag-picker';
  panel.innerHTML = `
    <div class="tag-picker__title">Tag this photo</div>
    <div class="tag-picker__hint">Pick everything that applies. Your picks are anonymous.</div>
    <div class="tag-picker__options"></div>
  `;
  const options = panel.querySelector('.tag-picker__options') as HTMLElement;

  defs.forEach((def) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'tag-option' + (def.public ? '' : ' tag-option--report');
    button.title = def.description;
    const setLabel = (tagged: boolean) => {
      button.innerHTML = `<span class="tag-option__emoji">${def.emoji}</span><span class="tag-option__label">${escapeHTML(def.display_name)}</span>${tagged ? '<span class="tag-option__check">✓</span>' : ''}`;
    };
    const alreadyTagged = hasMyTag(sightingId, def.name);
    setLabel(alreadyTagged);
    if (alreadyTagged) {
      button.classList.add('is-tagged');
      button.disabled = true;
    }
    button.addEventListener('click', () => {
      if (button.disabled) return;
      button.classList.add('is-tagged');
      button.disabled = true;
      setLabel(true);
      submitTag(sightingId, def.name);
      onTagged?.(def.name);
    });
    options.appendChild(button);
  });

  return panel;
}

/** Lazily-created singleton modal that hosts the tag picker. */
let modalEl: HTMLElement | null = null;

function ensureModal(): HTMLElement {
  if (modalEl) return modalEl;
  const overlay = document.createElement('div');
  overlay.className = 'tag-modal';
  overlay.setAttribute('role', 'dialog');
  overlay.setAttribute('aria-modal', 'true');
  overlay.innerHTML = `
    <div class="tag-modal__panel">
      <button type="button" class="tag-modal__close" aria-label="Close">×</button>
      <div class="tag-modal__body"></div>
    </div>
  `;
  overlay.addEventListener('click', (event) => {
    if (event.target === overlay) closeTagModal();
  });
  (overlay.querySelector('.tag-modal__close') as HTMLElement).addEventListener('click', closeTagModal);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeTagModal();
  });
  document.body.appendChild(overlay);
  modalEl = overlay;
  return overlay;
}

export function closeTagModal(): void {
  modalEl?.classList.remove('is-open');
}

/** Open the tag picker for a photo in a centered modal. */
export function openTagModal(
  sightingId: number | string,
  defs: TagDefinition[],
  onTagged?: (tag: string) => void
): void {
  const overlay = ensureModal();
  const body = overlay.querySelector('.tag-modal__body') as HTMLElement;
  body.innerHTML = '';
  body.appendChild(buildTagPicker(sightingId, defs, onTagged));
  overlay.classList.add('is-open');
}
