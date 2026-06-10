# commodity-weather-feeds

Keyless, scheduled aggregators that turn upstream weather data into small JSON signals for
commodity weather-tail prediction markets. Each feed pre-computes a production-weighted index
once, so a downstream LLM resolver only has to *fetch-and-read-one-field* (high reliability)
rather than navigate raw satellite/reanalysis data (unreliable).

Published via GitHub Pages from `docs/`.

## Feeds

| Feed | File | Signal | Source (keyless) |
|---|---|---|---|
| **Coffee VPD** | `docs/coffee_vpd.json` | Brazil arabica flowering-window (Sep15–Oct31) production-weighted vapor pressure deficit | NASA POWER daily T2M + dewpoint → FAO-56 VPD |
| **Corn VHI** | `docs/corn_vhi.json` | US Corn Belt corn-area-weighted Vegetation Health Index | NOAA STAR Blended VHP 4km |

Each feed's own README (`coffee_vpd/`, `corn_vhi/`) has the methodology, dose-response, and
backtest.

## URLs (once Pages is enabled)

```
https://<owner>.github.io/commodity-weather-feeds/coffee_vpd.json
https://<owner>.github.io/commodity-weather-feeds/corn_vhi.json
```

A measurable's resolver prompt fetches the URL and returns a single field (e.g.
`latest_window.weighted_vpd_kpa`).

## Refresh

`.github/workflows/refresh.yml` runs weekly (Wed 18:00 UTC) + manual dispatch, regenerates both
JSONs into `docs/`, and commits.

## Run locally

```bash
python coffee_vpd/aggregate_vpd.py docs/coffee_vpd.json     # stdlib only
python corn_vhi/aggregate_vhi.py docs/corn_vhi.json         # needs corn_vhi/requirements.txt + NetCDF
```
