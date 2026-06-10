#!/usr/bin/env python3
"""
Brazil arabica FROST event-trigger aggregator.

The explosive, near-binary half of the coffee weather tail (vs the gradual VPD/drought
trade). Frost in the Brazilian arabica belt during the austral winter (Jun-Aug) is the
single largest price-shock driver in softs (1975 Black Frost, 1994 twin frost, 2021
quadruple frost -> KC +10% in a session). It is a binary/severity event, NOT a continuous
dose-response, so the measurable is a frost-night COUNT, not a level.

Signal: daily minimum 2 m AIR temperature (NOT satellite LST — LST vs ground min-air-temp
R^2 only 0.12-0.57, refuted as a standalone frost detector). Counts "frost-risk nights" =
days on which the coldest belt reference point fell to <= the frost threshold during the
winter window. Radiative-frost coffee damage begins around 4 C ambient (leaf temp drops
several degrees below air temp on clear calm nights).

Data: NASA POWER daily T2M_MIN (keyless, global, 1981-present). Frost-prone reference points
skew SOUTH/high (where radiative frost actually bites): Sul de Minas, SP Mogiana, and the
historic Parana belt — NOT tropical Cerrado Mineiro.

    python aggregate_frost.py [out.json]
"""
import sys, json, datetime as dt
from urllib.request import urlopen
from urllib.parse import urlencode

POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
FILL = -999.0

# Frost-prone arabica reference points (coldest-relevant; south/high elevation).
POINTS = [
    {"key": "sul_de_minas_varginha", "name": "Sul de Minas (Varginha)", "lat": -21.55, "lon": -45.43},
    {"key": "sul_de_minas_pocos",    "name": "Sul de Minas (Pocos de Caldas)", "lat": -21.79, "lon": -46.56},
    {"key": "mogiana_franca",        "name": "Mogiana SP (Franca)", "lat": -20.54, "lon": -47.40},
    {"key": "parana_carlopolis",     "name": "Parana (Carlopolis, historic frost belt)", "lat": -23.43, "lon": -49.72},
]

WINTER_START = (6, 1)    # Jun 1
WINTER_END   = (8, 31)   # Aug 31
FROST_THRESHOLD_C = 4.0  # frost-risk night: coldest belt point <= 4 C
BASELINE_FIRST_YEAR = 1982


def fetch_tmin(lat, lon, start, end):
    qs = urlencode({"parameters": "T2M_MIN", "community": "AG",
                    "longitude": lon, "latitude": lat,
                    "start": start, "end": end, "format": "JSON"})
    with urlopen(f"{POWER_URL}?{qs}", timeout=90) as r:
        data = json.load(r)
    p = data["properties"]["parameter"]["T2M_MIN"]
    return {d: v for d, v in p.items() if v is not None and v != FILL}


def in_winter(yyyymmdd):
    m, d = int(yyyymmdd[4:6]), int(yyyymmdd[6:8])
    return (m, d) >= WINTER_START and (m, d) <= WINTER_END


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else None
    today = dt.date.today()
    end = today.strftime("%Y%m%d")
    start = f"{BASELINE_FIRST_YEAR}0101"

    # belt-min Tmin per day = coldest of the reference points that day
    belt_min = {}   # date -> min Tmin across points
    per_point_latest = {}
    for pt in POINTS:
        series = fetch_tmin(pt["lat"], pt["lon"], start, end)
        for d, v in series.items():
            if d not in belt_min or v < belt_min[d]:
                belt_min[d] = v

    # per-winter frost stats
    winters = {}  # year -> {"frost_nights": n, "coldest_c": x}
    for d, v in belt_min.items():
        if not in_winter(d):
            continue
        y = int(d[:4])
        w = winters.setdefault(y, {"frost_nights": 0, "coldest_c": 99.0, "coldest_date": None})
        if v <= FROST_THRESHOLD_C:
            w["frost_nights"] += 1
        if v < w["coldest_c"]:
            w["coldest_c"] = v
            w["coldest_date"] = d

    # latest fully-available winter
    latest_year = today.year if (today.month, today.day) > WINTER_END else today.year - 1
    # if winter not started/complete yet, current-year stats are partial; report what exists
    latest = winters.get(latest_year, {"frost_nights": 0, "coldest_c": None, "coldest_date": None})
    # A prior-year winter is always complete; the current year's only once past Aug 31.
    season_complete = (latest_year < today.year) or ((today.month, today.day) > WINTER_END)

    hist = {str(y): {"frost_nights": w["frost_nights"], "coldest_c": round(w["coldest_c"], 1)}
            for y, w in sorted(winters.items())}

    result = {
        "generated_at_utc": dt.datetime.utcnow().isoformat() + "Z",
        "source": "NASA POWER daily T2M_MIN (2 m min air temp)",
        "signal": "Brazil arabica belt frost-risk nights (belt-coldest Tmin <= %.0fC), Jun1-Aug31" % FROST_THRESHOLD_C,
        "geography": "Frost-prone arabica points: Sul de Minas, Mogiana SP, Parana",
        "method": {
            "frost_threshold_c": FROST_THRESHOLD_C,
            "belt_min": "coldest of the reference points each day",
            "window": "Jun 1 - Aug 31 (austral winter)",
            "note": "2 m AIR temp, not satellite LST (LST refuted as standalone frost detector).",
        },
        "latest_winter": {
            "year": latest_year,
            "season_complete": season_complete,
            "frost_nights": latest["frost_nights"],
            "coldest_c": round(latest["coldest_c"], 1) if latest.get("coldest_c") not in (None, 99.0) else None,
            "coldest_date": latest.get("coldest_date"),
            "frost_event_flag": latest["frost_nights"] > 0,
        },
        "history_frost_nights": hist,
        "interpretation": {
            "frost_nights": "count of <=4C nights at the coldest belt point; 0 in most years, several in frost years",
            "trade": "EVENT-TRIGGER (binary/severity). Higher frost_nights = worse frost = KC-bullish.",
        },
    }
    txt = json.dumps(result, indent=2)
    print(txt)
    if out_path:
        with open(out_path, "w") as f:
            f.write(txt)


if __name__ == "__main__":
    main()
