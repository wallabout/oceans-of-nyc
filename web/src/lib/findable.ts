/**
 * Which Oceans count toward "how many are there to find". Mirrors the
 * ocean_findability view (database/migrations/20261007_1300_create_ocean_findability.sql):
 * an Ocean is inactive once it's missing from the latest TLC snapshot, and an
 * inactive Ocean nobody ever sighted leaves the denominator. A sighted Ocean
 * stays in it for good.
 *
 * Dates are 'YYYY-MM-DD' strings, so they compare as strings.
 */

export interface Findability {
  debut: string | null;
  lastReported: string | null;
  firstSighted: string | null;
  active: boolean;
}

function dateKey(value: unknown): string | null {
  const m = String(value ?? '').match(/^\d{4}-\d{2}-\d{2}/);
  return m ? m[0] : null;
}

function extreme(values: unknown[], pick: (a: string, b: string) => boolean): string | null {
  let best: string | null = null;
  for (const value of values) {
    const key = dateKey(value);
    if (key && (!best || pick(key, best))) best = key;
  }
  return best;
}

function lastReportedOn(vehicle: any): string | null {
  return extreme((vehicle.license_plates || []).map((p: any) => p.most_recently_reported_on), (a, b) => a > b);
}

/** The latest TLC snapshot date: the newest most_recently_reported_on of any plate. */
export function getLatestTlcReport(vehicles: any[]): string {
  let latest = '';
  for (const v of vehicles) {
    const last = lastReportedOn(v);
    if (last && last > latest) latest = last;
  }
  return latest;
}

export function getFindability(vehicle: any, latestTlcReport: string): Findability {
  const lastReported = lastReportedOn(vehicle);
  return {
    debut: extreme((vehicle.license_plates || []).map((p: any) => p.first_reported_on), (a, b) => a < b),
    lastReported,
    // Sighting timestamps carry the ET offset, so their date prefix is the ET date.
    firstSighted: extreme((vehicle.sightings || []).map((s: any) => s.timestamp), (a, b) => a < b),
    active: lastReported === latestTlcReport,
  };
}

/** Counted today: active, or sighted at least once. */
export function isFindable(f: Findability): boolean {
  return f.active || f.firstSighted !== null;
}

/** Counted as of `day`: debuted by then, and either still active then or already sighted. */
export function isFindableOn(f: Findability, day: string): boolean {
  if (f.debut && f.debut > day) return false;
  return f.active || (f.lastReported !== null && f.lastReported >= day) || (f.firstSighted !== null && f.firstSighted <= day);
}
