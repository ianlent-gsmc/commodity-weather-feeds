# US Corn Belt VHI aggregator

Lightweight pipeline that fetches NOAA STAR Blended Vegetation Health Products (VHP) 4km weekly NetCDF files, computes a harvested-corn-area-weighted average **Vegetation Health Index (VHI)** for the top-5 US corn states (Iowa, Illinois, Indiana, Nebraska, Minnesota), and publishes a JSON artifact at a static URL.

Built to serve as the resolution source for a prediction-market measurable `us_corn_belt_vhi_trailing4w` — a leading-indicator signal that demonstrably precedes WASDE (USDA's outlook process ingests the same upstream satellite signals through a 2-week consensus cycle).

## Why this exists

The Option-A bot probe failed: NOAA STAR publishes the data behind JavaScript/PHP visualization layers, and our LLM resolver (perplexity/sonar-pro) reaches the underlying numbers only ~1 in 3 attempts (the other 2 hit refusal-→-0 sentinels). The data exists; the bot just can't reliably navigate to it. So we pre-compute it once a week and publish a clean JSON.

## Output format

```json
{
  "generated_at_utc": "2026-06-05T18:05:42.123456+00:00",
  "source": "NOAA STAR Blended VHP 4km Weekly",
  "geography": "US Corn Belt — top-5 corn-producing states ...",
  "latest_week": {
    "year": 2026,
    "iso_week": 23,
    "file_url": "https://www.star.nesdis.noaa.gov/.../VHP.G04.C07.j02.P2026023.VH.nc",
    "weighted_vhi": 58.27,
    "per_state_vhi": {"iowa": 60.1, "illinois": 55.4, "indiana": 57.0, "nebraska": 59.8, "minnesota": 58.5},
    "pixel_counts": {"iowa": 5234, "illinois": 6122, ...}
  },
  "trailing_4week": {
    "weeks": [...],
    "mean_weighted_vhi": 57.95
  },
  "interpretation": { "vhi_scale": "0-100", "0-30": "severe stress / drought", ... }
}
```

## Local run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python aggregate_vhi.py vhi_corn_belt.json
```

Outputs `vhi_corn_belt.json` and prints the same to stdout.

## Deploy as a public static URL via GitHub Pages

1. Push this directory to a GitHub repo (public).
2. Repo Settings → Pages → Source: **Deploy from a branch**; Branch: `main`, folder: `/docs`.
3. The workflow at `.github/workflows/weekly-vhi.yml` runs every Wednesday 18:00 UTC, writes `docs/vhi_corn_belt.json` + `docs/latest.json`, and commits.
4. The published URL becomes: `https://<your-user>.github.io/<repo>/latest.json`.

The measurable's `prompt` field then directs the bot to fetch that URL and return `latest_week.weighted_vhi` (or `trailing_4week.mean_weighted_vhi`).

## Methodology notes

- **State extraction**: bounding-box approximation (not polygon-clipped). State-level mean VHI is within ~5% of polygon-clipped at 4km resolution. Polygon clipping would require `rioxarray` + `geopandas` — heavier dependency chain, not justified at this scale.
- **Corn-area weights**: hardcoded from USDA NASS *Acreage* (latest crop year). **Refresh annually** — see `CORN_AREA_WEIGHTS` in `aggregate_vhi.py`.
- **Satellite preference**: when multiple files exist for the same week, picks `j02` (NOAA-21) > `j01` (NOAA-20) > `npp` (S-NPP). All carry VIIRS; the blended product is harmonized.
- **VHI valid range**: 0 < VHI ≤ 100. Fill value `-999` and any non-finite values are excluded from the mean.
- **Trailing window**: latest 4 ISO weeks. Adjust `TRAILING_WEEKS` constant.

## Open follow-ups

- Refresh `CORN_AREA_WEIGHTS` from USDA NASS Acreage (June 30 release) annually.
- Consider adding polygon-clipping via `rioxarray` if state-level fidelity becomes load-bearing.
- Extend to Brazil Mato Grosso, EU NUTS-2, or other geographies (same VHP 4km product is global).
