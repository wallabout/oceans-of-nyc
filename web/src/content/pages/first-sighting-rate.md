---
title: "Introducing First-Sighting Rate"
posted: 2026-05-01
description: "A new graph on the stats page shows how often new Oceans are being found — versus how often we'd expect, given the TLC fleet."
author: "Oceans of NYC"
category: "Features"
---

> Well, this is interesting. We've got a new graph on [oceansofnyc.com/stats/](/stats) which shows the "first sighting rate" on each day, compared to what we'd expect given the TLC data.

<div class="inline-chart"><canvas id="firstSightingRateChartInline"></canvas></div>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
<script>
(function () {
  const TEXT_COLOR = 'rgba(0,0,0,0.7)';
  const CHART_COLOR = '#6b9bd1';
  async function run() {
    const isLocal = window.location.hostname === 'localhost';
    const url = isLocal ? '/daily_sightings.json' : 'https://cdn.oceansofnyc.com/web/daily_sightings.json';
    const { daily_sightings } = await (await fetch(url)).json();
    const scatterData = [], lineData = [], rollingData = [];
    for (const d of daily_sightings) {
      const x = new Date(d.date + 'T12:00:00');
      if (d.first_sighting_rate != null) scatterData.push({ x, y: d.first_sighting_rate * 100 });
      if (d.expected_first_sighting_rate != null) lineData.push({ x, y: d.expected_first_sighting_rate * 100 });
      if (d.rolling_first_sighting_rate != null) rollingData.push({ x, y: d.rolling_first_sighting_rate * 100 });
    }
    new Chart(document.getElementById('firstSightingRateChartInline'), {
      data: { datasets: [
        { type: 'scatter', label: 'Daily Actual', data: scatterData, backgroundColor: CHART_COLOR, pointRadius: 3 },
        { type: 'line', label: 'Last 200', data: rollingData, borderColor: CHART_COLOR, backgroundColor: 'transparent', tension: 0.2, pointRadius: 0 },
        { type: 'line', label: 'Expected', data: lineData, borderColor: '#e07b53', backgroundColor: 'transparent', tension: 0.2, pointRadius: 0 }
      ]},
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: true, position: 'top', labels: { color: TEXT_COLOR, usePointStyle: true } } },
        scales: {
          x: { type: 'time', time: { unit: 'day', displayFormats: { day: 'MMM d' }, tooltipFormat: 'MMM d, yyyy' }, min: '2025-12-06', grid: { display: false }, ticks: { color: TEXT_COLOR, font: { size: 11 } }, border: { color: 'rgba(0,0,0,0.1)' } },
          y: { min: 0, grid: { color: 'rgba(0,0,0,0.1)' }, ticks: { color: TEXT_COLOR, font: { size: 11 }, callback: v => Number(v).toFixed(0) + '%' }, border: { display: false }, title: { display: true, text: '% of Sightings', color: TEXT_COLOR } }
        }
      }
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', run);
  else run();
})();
</script>
<style>.inline-chart { position: relative; height: 300px; margin: 24px 0; } @media (max-width: 768px) { .inline-chart { height: 250px; } }</style>

The **first-sighting rate** is the fraction of recent sightings that turned out to be brand-new Oceans, i.e., not already in the catalog. Early on, it was near 100% — almost every sighting added a new vehicle. As the catalog has filled in, the rate has dropped, because more and more sightings are duplicates of Oceans we've already logged.

The interesting move is comparing the *actual* first-sighting rate to a *theoretical* rate computed from the NYC TLC dataset. If we had perfect, uniform random sampling of every Ocean on the road, what fraction of new sightings would we expect to be first-time finds? That's the baseline.

Where the actual rate sits relative to that baseline tells us something:

- **Below the line** — we're systematically missing some segment of the fleet. Same vehicles being seen over and over, while others sit unwatched.
- **At the line** — sampling is roughly uniform.
- **Above the line** — contributors are doing a better-than-random job of seeking out unseen Oceans. Quite possibly the case.

The graph is live on the [stats page](/stats). It's also the basis for [Ocean Points](/p/ocean-points), which scale inversely with the recent first-sighting rate: rarer finds, more points.
