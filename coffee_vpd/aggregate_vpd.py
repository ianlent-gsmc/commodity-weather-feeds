#!/usr/bin/env python3
"""
Brazil arabica flowering-window VPD aggregator.

The continuous-stress weather-tail signal for arabica coffee (ICE 'KC'), built on
the same Option-B pattern as the corn VHI aggregator: keyless feed -> production-
weighted index -> static JSON at a stable URL that a measurable prompt fetches.

Signal: vapor pressure deficit (VPD) during the Sep-Oct flowering window, the
single highest-alpha drought/heat indicator for arabica yield per Kath et al.
2022 (Nature Food) -- VPD outranks temperature, precipitation, and soil moisture;
yield declines rapidly past ~0.82 kPa. Dose-response: -4.0% yield per +0.1 kPa
(Wang et al. 2025, Yunnan GAM).

Data: NASA POWER daily point API (keyless, global, 1981-present). VPD is derived
from 2 m mean temperature (T2M) and 2 m dew/frost point (T2MDEW):
    es(T) = 0.6108 * exp(17.27*T / (T+237.3))   [kPa]   (FAO-56)
    VPD   = es(T2M) - es(T2MDEW)

Production weights and representative points are arabica-region approximations
(judgment-calibrated; refine from CONAB regional output). Usage:
    python aggregate_vpd.py [out.json]
"""
import sys
import json
import math
import datetime as dt
from urllib.request import urlopen
from urllib.parse import urlencode

# --- configuration -----------------------------------------------------------

POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
FILL = -999.0

# Arabica sub-regions: representative point + production weight (normalized).
# Weights approximate arabica share among Brazil's main arabica regions
# (Sul de Minas largest; Cerrado Mineiro + Matas de Minas mid; SP Mogiana smaller).
# REFRESH from CONAB regional output; these are first-cut judgment weights.
REGIONS = [
    {"key": "sul_de_minas",   "name": "Sul de Minas (MG)",     "lat": -21.55, "lon": -45.43, "weight": 0.40},
    {"key": "cerrado_mineiro","name": "Cerrado Mineiro (MG)",  "lat": -18.94, "lon": -46.99, "weight": 0.22},
    {"key": "matas_de_minas", "name": "Matas de Minas (MG)",   "lat": -20.26, "lon": -42.03, "weight": 0.22},
    {"key": "mogiana_sp",     "name": "Mogiana (SP)",          "lat": -20.54, "lon": -47.40, "weight": 0.16},
]

FLOWERING_START = (9, 15)   # Sep 15
FLOWERING_END   = (10, 31)  # Oct 31
BASELINE_FIRST_YEAR = 2001  # climatology start
KATH_THRESHOLD_KPA = 0.82   # Kath 2022 abrupt-decline threshold
DOSE_PCT_PER_0P1_KPA = -4.0 # Wang 2025: -4.0% yield per +0.1 kPa VPD at flowering


def es_kpa(t_c: float) -> float:
    """Saturation vapor pressure (kPa) at temperature t_c (deg C), FAO-56."""
    return 0.6108 * math.exp(17.27 * t_c / (t_c + 237.3))


def fetch_power(lat: float, lon: float, start: str, end: str) -> dict:
    """Fetch daily T2M + T2MDEW from NASA POWER. Returns {date: vpd_kpa}."""
    qs = urlencode({
        "parameters": "T2M,T2MDEW",
        "community": "AG",
        "longitude": lon,
        "latitude": lat,
        "start": start,
        "end": end,
        "format": "JSON",
    })
    with urlopen(f"{POWER_URL}?{qs}", timeout=60) as r:
        data = json.load(r)
    p = data["properties"]["parameter"]
    t2m, tdew = p["T2M"], p["T2MDEW"]
    out = {}
    for day, t in t2m.items():
        td = tdew.get(day)
        if t is None or td is None or t == FILL or td == FILL:
            continue
        vpd = es_kpa(t) - es_kpa(td)
        if vpd < 0:  # numerically possible when T2MDEW ~ T2M; clamp
            vpd = 0.0
        out[day] = vpd
    return out


def in_window(yyyymmdd: str) -> bool:
    m, d = int(yyyymmdd[4:6]), int(yyyymmdd[6:8])
    return (m, d) >= FLOWERING_START and (m, d) <= FLOWERING_END


def window_means_by_year(daily_vpd: dict) -> dict:
    """Mean flowering-window VPD per year from a {YYYYMMDD: vpd} dict."""
    buckets = {}
    for day, vpd in daily_vpd.items():
        if in_window(day):
            buckets.setdefault(int(day[:4]), []).append(vpd)
    return {y: sum(v) / len(v) for y, v in buckets.items() if v}


def mean_std(xs):
    n = len(xs)
    m = sum(xs) / n
    var = sum((x - m) ** 2 for x in xs) / n if n > 1 else 0.0
    return m, math.sqrt(var)


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else None
    today = dt.date.today()
    end = today.strftime("%Y%m%d")
    start = f"{BASELINE_FIRST_YEAR}0101"

    # Latest fully-available flowering window: if we're past Oct 31 this year use
    # this year, else the previous year.
    latest_year = today.year if (today.month, today.day) > FLOWERING_END else today.year - 1

    per_region = {}
    weighted_year_vpd = {}   # year -> production-weighted national VPD
    total_w = sum(r["weight"] for r in REGIONS)

    for r in REGIONS:
        daily = fetch_power(r["lat"], r["lon"], start, end)
        yearly = window_means_by_year(daily)
        per_region[r["key"]] = {
            "name": r["name"],
            "weight": r["weight"],
            "latest_window_vpd_kpa": round(yearly.get(latest_year), 3) if latest_year in yearly else None,
            "n_years": len(yearly),
        }
        for y, v in yearly.items():
            weighted_year_vpd.setdefault(y, 0.0)
            weighted_year_vpd[y] += (r["weight"] / total_w) * v

    # Some regions may lack the latest year if POWER hasn't filled it; only keep
    # years where all regions contributed (sum of weights ~ total_w).
    baseline_years = [y for y in weighted_year_vpd
                      if BASELINE_FIRST_YEAR <= y < latest_year]
    baseline_vals = [weighted_year_vpd[y] for y in sorted(baseline_years)]
    clim_mean, clim_std = mean_std(baseline_vals)

    latest_vpd = weighted_year_vpd.get(latest_year)
    anomaly_kpa = (latest_vpd - clim_mean) if latest_vpd is not None else None
    anomaly_z = (anomaly_kpa / clim_std) if (anomaly_kpa is not None and clim_std) else None
    # Dose-response yield deviation (%) relative to climatology.
    yield_dev_pct = (DOSE_PCT_PER_0P1_KPA * anomaly_kpa / 0.1) if anomaly_kpa is not None else None

    result = {
        "generated_at_utc": dt.datetime.utcnow().isoformat() + "Z",
        "source": "NASA POWER daily (T2M, T2MDEW) -> FAO-56 VPD",
        "signal": "Brazil arabica flowering-window (Sep15-Oct31) production-weighted VPD",
        "geography": "Brazil arabica belt: Sul de Minas, Cerrado Mineiro, Matas de Minas, Mogiana SP",
        "method": {
            "vpd": "es(T2M) - es(T2MDEW), FAO-56; daily then window-mean",
            "weights": {r["key"]: r["weight"] for r in REGIONS},
            "kath_threshold_kpa": KATH_THRESHOLD_KPA,
            "dose_pct_per_0p1_kpa": DOSE_PCT_PER_0P1_KPA,
            "baseline_years": f"{BASELINE_FIRST_YEAR}-{latest_year-1}",
        },
        "latest_window": {
            "year": latest_year,
            "weighted_vpd_kpa": round(latest_vpd, 3) if latest_vpd is not None else None,
            "exceeds_kath_threshold": (latest_vpd > KATH_THRESHOLD_KPA) if latest_vpd is not None else None,
            "anomaly_kpa": round(anomaly_kpa, 3) if anomaly_kpa is not None else None,
            "anomaly_z": round(anomaly_z, 2) if anomaly_z is not None else None,
            "implied_yield_dev_pct": round(yield_dev_pct, 1) if yield_dev_pct is not None else None,
        },
        "climatology": {
            "mean_vpd_kpa": round(clim_mean, 3),
            "std_vpd_kpa": round(clim_std, 3),
            "n_years": len(baseline_vals),
        },
        "per_region": per_region,
        "history_weighted_vpd_kpa": {str(y): round(weighted_year_vpd[y], 3)
                                     for y in sorted(weighted_year_vpd)},
        "interpretation": {
            "scale": "kPa; higher = drier air = more flowering stress",
            "note": "Mean-temp VPD (conservative). Daytime VPD via Tmax is a v2 refinement; "
                    "absolute level lower than Kath's seasonal construction but internally "
                    "consistent for the anomaly/z-score. Positive anomaly => yield-negative => KC-bullish.",
        },
    }

    txt = json.dumps(result, indent=2)
    print(txt)
    if out_path:
        with open(out_path, "w") as f:
            f.write(txt)


if __name__ == "__main__":
    main()
