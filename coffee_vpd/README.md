# Brazil arabica flowering-VPD aggregator

The **continuous-stress weather-tail signal** for arabica coffee (ICE `KC`) — the drought
trade. Computes a production-weighted **vapor pressure deficit (VPD)** over the Brazilian
arabica belt during the Sep 15–Oct 31 flowering window and publishes a JSON artifact for a
prediction-market measurable to resolve against.

This is the coffee analog of the corn VHI aggregator (`../vhi_aggregator/`) and the first
concrete instance of the `create-weather-tail-bot` **continuous-stress template**.

## Why VPD, why flowering

From an adversarially-verified deep-research run (memory: `coffee-weather-signal-research.md`):
- **Kath et al. 2022 (*Nature Food*, 13 countries):** VPD is the single most important
  seasonal indicator of arabica yield — it **outranks temperature, precipitation, AND soil
  moisture.** Yield declines rapidly past **0.82 kPa**.
- **Wang et al. 2025 (Yunnan GAM):** **−4.0% yield per +0.1 kPa VPD** at flowering. VPD beat
  SPI and SPEI.
- Flowering (Sep–Oct) is the window where below-normal rain / high VPD causes floral abortion
  and reduced fruits-per-rosette — the proximate mechanism translating weather into yield loss.

## Signal & method

- **Data:** NASA POWER daily point API — **keyless, global, 1981-present.** No CDS/ERA5 key.
- **VPD (FAO-56):** `es(T) = 0.6108·exp(17.27·T/(T+237.3))`; `VPD = es(T2M) − es(T2MDEW)`,
  daily then window-mean. (Mean-temp VPD; a daytime Tmax-based VPD is a v2 refinement — higher
  absolute level, but the anomaly/z-score is what the measurable trades.)
- **Production-weighted** across four arabica regions (representative points):
  Sul de Minas 0.40, Cerrado Mineiro 0.22, Matas de Minas 0.22, Mogiana SP 0.16.
  *Weights are judgment-calibrated first cuts — refresh from CONAB regional output.*
- **Output:** latest-window VPD, anomaly vs 2001–climatology, z-score, threshold flag, and an
  implied yield-deviation % via the dose-response.

## Run

```bash
python3 aggregate_vpd.py vpd_arabica.json   # no dependencies — stdlib only
```

4 API calls (one per region), ~5 s. Prints JSON and writes the file.

## Backtest (validates the drought trade, isolates it from frost)

Highest flowering-VPD years vs known arabica price tails:

| Rank | Year | VPD (kPa) | z | Known market event |
|---|---|---|---|---|
| 1 | 2015 | 1.68 | +1.88 | El Niño drought, 2014–15 rally |
| 2 | 2014 | 1.58 | +1.52 | Great 2014 drought — arabica ~doubled |
| 3 | 2007 | 1.53 | +1.33 | 2007/08 tightness |
| 4 | 2024 | 1.50 | +1.22 | drought → 2024–25 record run |
| 6 | 2020 | 1.43 | +0.93 | dryness into the 2020–21 rally |
| 7 | 2025 | 1.42 | +0.91 | current "driest since 1981"; Volcafe cut to 34.4M bags |
| … | 2021 | 1.14 | **−0.17** | **flowering OK — 2021 tail was the JULY FROST, not drought** |

The top-VPD years are the drought-rally years; 2021 (the frost year) reads benign — the feed
captures the **drought** trade specifically. The frost trade needs the separate **event-trigger
template** (2 m min-air-temp over the belt, Jun–Aug).

## Deploy as a static URL (same pattern as the VHI feed)

1. Push to a public repo; enable GitHub Pages from `/docs`.
2. A weekly (in-window) Action runs `aggregate_vpd.py docs/latest.json` and commits.
3. The measurable prompt fetches the URL and returns `latest_window.weighted_vpd_kpa`
   (or `implied_yield_dev_pct`). Fetch-and-read-one-field >> free-form extraction.

## Measurable hookup (next step)

A `brazil_arabica_flowering_vpd` measurable on the clone: monthly cadence, growing-season
settlements, strike ladder centered on the climatology (~1.18 kPa) with rungs spanning the
observed range (~0.7–1.7). Hooks into the existing coffee cluster (usd_brl 135601, certified
arabica stocks 135602, Brazil/Vietnam exports). Because VPD is a level (not signed), no
negative rung needed — but SEED-FIRST the resolver and center on the live reading.

## Maintenance
- Refresh region production weights from CONAB annually.
- Window/threshold are constants at the top of `aggregate_vpd.py`.
- Re-point to other commodities by swapping REGIONS + window (cocoa, sugar, cotton, soy).
