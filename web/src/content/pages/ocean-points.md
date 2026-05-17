---
title: "What are Ocean Points (◎p)?"
updated: 2026-05-13
description: "Ocean Points reward contributors who find Oceans we've never seen before — and the harder they get to find, the more valuable they become."
author: "Oceans of NYC"
category: "FAQ"
---

We've added a new way to measure the value of a sighting: **Ocean Points (◎p)**.

## What are Ocean Points?

Ocean Points are awarded for first sightings — the moment a contributor spots an Ocean that has never been reported before. They're extremely important and meaningful internet points.

The formula is simple:

**◎p = 1 ÷ (first-sighting rate over the previous 200 sightings)**

When we started, almost every sighting was a first sighting. The first-sighting rate was high, which meant ◎p was low — just 1 point per discovery. As more Oceans have been found, first sightings have become rarer. That rarity is now reflected in the points.

<div class="inline-chart"><canvas id="oceanPointsChartInline"></canvas></div>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0/dist/chartjs-adapter-date-fns.bundle.min.js"></script>
<script>
(function () {
  const TEXT_COLOR = 'rgba(0,0,0,0.7)';
  const CHART_COLOR = '#6b9bd1';
  async function run() {
    const isLocal = window.location.hostname === 'localhost';
    const url = isLocal ? '/oceans.json' : 'https://cdn.oceansofnyc.com/web/oceans.json';
    const { vehicles } = await (await fetch(url)).json();
    const data = [];
    for (const v of vehicles) {
      if (!v.sightings?.length) continue;
      for (const s of v.sightings) {
        if (s.vehicle_sighting_index === 1 && s.ocean_points > 0) {
          data.push({ x: new Date(s.timestamp), y: s.ocean_points });
        }
      }
    }
    data.sort((a, b) => a.x - b.x);
    new Chart(document.getElementById('oceanPointsChartInline'), {
      type: 'line',
      data: { datasets: [{ label: 'Ocean Points', data, borderColor: CHART_COLOR, backgroundColor: 'transparent', tension: 0.1, pointRadius: 0 }] },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { type: 'time', time: { unit: 'day', displayFormats: { day: 'MMM d' }, tooltipFormat: 'MMM d, yyyy' }, min: '2025-12-06', grid: { display: false }, ticks: { color: TEXT_COLOR, font: { size: 11 } }, border: { color: 'rgba(0,0,0,0.1)' }, title: { display: true, text: 'Date', color: TEXT_COLOR, align: 'end' } },
          y: { min: 0, grid: { color: 'rgba(0,0,0,0.1)' }, ticks: { color: TEXT_COLOR, font: { size: 11 } }, border: { display: false }, title: { display: true, text: '◎p per First Sighting', color: TEXT_COLOR } }
        }
      }
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', run);
  else run();
})();
</script>
<style>.inline-chart { position: relative; height: 300px; margin: 24px 0; } @media (max-width: 768px) { .inline-chart { height: 250px; } }</style>

## What does it do for the game?

1. Contributors joining today will be hard pressed to catch up with some of our long time players in Sightings or First Sightings, but there are big ◎p opportunities in the future. New contributors can grab some huge wins if they find the unseen Oceans. 
2. It's possible that we're not looking in the right places for the Oceans we've never seen. If we're all looking in the same place and driving first-sighting rates down, ◎p will be relative easy to get if you're off finding new territory. 

## Why 200 sightings?

The trailing 200 sightings give a reasonable estimate of how hard it actually is, right now, to go out and find a new Ocean. Not how hard it was six months ago, and not a theoretical ceiling — just a rolling window of recent experience. 100 was too erratic, 500 seems too slow. 

## How high can ◎p get?

If 199 sightings go by without a new Ocean and then someone finds one, that contributor earns **200 ◎p**. If the window ever needs to stretch beyond 200, we'll extend it. For now, 200 is the cap.

## We've backfilled everything

◎p has been calculated for every first sighting in the dataset, going back to the beginning. The points reflect what was actually true at the time — how rare a first sighting was when it happened.

## Where to find ◎p

- **The feeds page** — first sightings now show their ◎p value
- **Your confirmation message** — when you report a first sighting, you'll see how many ◎p you earned
- **The stats page** — ◎p totals appear alongside total sightings and first sighting counts by contributor

![](https://cdn.oceansofnyc.com/web/img/OP_screenshot.png)

If you're out there finding new Oceans, you're earning points. Go find one.
