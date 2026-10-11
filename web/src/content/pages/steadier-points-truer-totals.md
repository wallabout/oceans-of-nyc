---
title: "Steadier Ocean Points and a Truer Count"
posted: 2026-10-07
description: "◎p now uses a 400-sighting window, the stats page splits out first sightings, and Oceans that left the TLC database unseen no longer count toward the total."
author: "Oceans of NYC"
category: "Features"
---

We shipped three changes this morning. All of them are about making the numbers say what they mean.

## Ocean Points use a longer window

[Ocean Points (◎p)](/p/ocean-points) are 1 ÷ the first-sighting rate over recent sightings. Until today, "recent" meant the last 200 sightings.

When most sightings were first sightings, 200 worked fine. Now first sightings are rare, and a 200-sighting window has only a handful of them in it, so ◎p swung a lot from one discovery to the next. One lucky stretch could cut the value of the next find in half.

The window is now **400 sightings**. ◎p still rises as Oceans get harder to find, but it moves more smoothly. The cap goes up too: if 399 sightings go by without a new Ocean, the next first sighting is worth **400 ◎p**.

◎p is calculated from the sighting history, so **every past sighting has been recalculated** with the new window. Your ◎p total may have changed a little, in either direction. Nobody did anything differently. The ruler changed.

## First sightings get their own chart

The [stats page](/stats) used to put total sightings and first sightings on one cumulative chart. Total sightings grow much faster, so the first-sightings line ended up as a flat stripe along the bottom.

They're now two charts:

- **Cumulative Sightings** shows total sightings by itself.
- **Cumulative First Sightings** plots first sightings next to a dashed line for **how many Oceans were in the TLC database on each day**. The dashed line steps up when new Oceans debut. Hover over any day to see first sightings as a share of the Oceans that existed then.

The second chart is the one to watch. The gap between the two lines is how many Oceans are still out there.

## Oceans that left unseen don't count against us

The TLC publishes a fresh snapshot of registered vehicles regularly. When an Ocean is missing from the latest snapshot, we call it **inactive**. That's the same rule as the Inactive filter on the [home page](/) grid. Some inactive Oceans were sighted before they went. Others left the fleet before anyone saw them.

The second group can't be found anymore, so it no longer makes sense to count them as Oceans left to find. Starting today, **inactive Oceans that nobody sighted drop out of the total**. Any Ocean that was sighted at least once stays in it, even if it later goes inactive. Your sighting still counts.

This affects:

- **"X of Y Oceans found"** on the site header, and the progress bar in our Bluesky posts
- **The expected first-sighting rate** on the stats page, which is now based on Oceans you could actually have found on each day
- **The Oceans to Find line**, which now drops Oceans when they go inactive without being sighted
- **The sighting count distribution**, where the "0 sightings" bucket only counts Oceans that were still findable on the slider date
- **The TLC first report chart**, which leaves out inactive Oceans that were never sighted

Y gets smaller, so the percentage found goes up. We didn't move the goalposts. We took away the ones nobody could reach.

Go find the rest.
