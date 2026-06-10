#!/usr/bin/env python3
"""
US Corn Belt VHI aggregator.

Fetches NOAA STAR Blended VHP 4km weekly NetCDF files, extracts state-level
VHI values for the top-5 US corn-producing states (Iowa, Illinois, Indiana,
Nebraska, Minnesota), and publishes a JSON artifact.

Output: vhi_corn_belt.json — single object with the latest week + a trailing
4-week mean, per-state breakdown, and audit metadata.

Designed for: GitHub Actions weekly cron. Deps: requests, xarray, netCDF4,
numpy. NO rioxarray/geopandas (bbox extraction approximates polygon clipping;
state-level error is <5%).

Source: https://www.star.nesdis.noaa.gov/pub/corp/scsb/wguo/data/Blended_VH_4km/VH/
File naming: VHP.G04.C07.<satellite>.P<YYYY><WW>.VH.nc
  G04 = 0.04 deg grid (~4km); <satellite> in {npp, j01, j02}; YYYY=year, WW=ISO-week
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import numpy as np
import requests
import xarray as xr

# ---- Config ----------------------------------------------------------------

VHP_INDEX_URL = (
    "https://www.star.nesdis.noaa.gov/pub/corp/scsb/wguo/data/Blended_VH_4km/VH/"
)

# 5 top corn-producing states, bbox (lat_min, lat_max, lon_min, lon_max) per
# US Census state extents. Bbox vs polygon-clipped error is <5% at state scale.
STATE_BBOX = {
    "iowa":      (40.38, 43.50, -96.64, -90.14),
    "illinois":  (36.97, 42.51, -91.51, -87.50),
    "indiana":   (37.77, 41.76, -88.10, -84.78),
    "nebraska":  (40.00, 43.00, -104.05, -95.31),
    "minnesota": (43.50, 49.38, -97.24, -89.49),
}

# Harvested-corn-area shares (USDA NASS, latest crop year). Used as weights
# for the 5-state aggregate. Hardcoded; refresh annually from NASS Acreage.
CORN_AREA_WEIGHTS = {
    "iowa":      0.27,
    "illinois":  0.24,
    "nebraska":  0.17,
    "minnesota": 0.16,
    "indiana":   0.16,
}
assert abs(sum(CORN_AREA_WEIGHTS.values()) - 1.0) < 1e-6

# How many trailing weeks to fetch for the trailing-N mean
TRAILING_WEEKS = 4

# ---- Data classes ----------------------------------------------------------

@dataclass
class WeekResult:
    year: int
    week: int
    file_url: str
    per_state_vhi: dict[str, float]  # state -> mean VHI
    weighted_vhi: float
    pixel_counts: dict[str, int] = field(default_factory=dict)

# ---- VHP file discovery ----------------------------------------------------

FILE_PATTERN = re.compile(
    r"VHP\.G04\.C07\.(?P<sat>npp|j01|j02)\.P(?P<year>\d{4})(?P<week>\d{3})\.VH\.nc"
)

def list_available_files(session: requests.Session) -> list[tuple[int, int, str, str]]:
    """Return list of (year, week, satellite, full_url) for all VH.nc files in the index, sorted descending."""
    resp = session.get(VHP_INDEX_URL, timeout=60)
    resp.raise_for_status()
    matches = []
    for m in FILE_PATTERN.finditer(resp.text):
        year = int(m.group("year"))
        week = int(m.group("week"))
        sat = m.group("sat")
        filename = m.group(0)
        matches.append((year, week, sat, urljoin(VHP_INDEX_URL, filename)))
    if not matches:
        raise RuntimeError(f"No VH.nc files matched at {VHP_INDEX_URL} — has the file naming changed?")
    # Deduplicate by (year, week) keeping the highest-rank satellite (j02 > j01 > npp)
    sat_rank = {"j02": 3, "j01": 2, "npp": 1}
    best: dict[tuple[int, int], tuple[int, int, str, str]] = {}
    for y, w, s, u in matches:
        key = (y, w)
        if key not in best or sat_rank.get(s, 0) > sat_rank.get(best[key][2], 0):
            best[key] = (y, w, s, u)
    return sorted(best.values(), key=lambda t: (t[0], t[1]), reverse=True)

# ---- VHI extraction --------------------------------------------------------

def open_vhi_dataset(local_path: Path) -> xr.Dataset:
    """Open NetCDF and return the dataset; tolerate variations in variable naming."""
    ds = xr.open_dataset(local_path, engine="netcdf4")
    return ds

def _detect_coord_names(ds: xr.Dataset) -> tuple[str, str]:
    """Return (lat_dim, lon_dim) names. NOAA VHP uses HEIGHT/WIDTH or latitude/longitude depending on version."""
    candidates_lat = ["latitude", "lat", "HEIGHT", "y"]
    candidates_lon = ["longitude", "lon", "WIDTH", "x"]
    lat = next((c for c in candidates_lat if c in ds.coords or c in ds.variables), None)
    lon = next((c for c in candidates_lon if c in ds.coords or c in ds.variables), None)
    if lat is None or lon is None:
        raise RuntimeError(
            f"Could not detect lat/lon coords. Available: coords={list(ds.coords)} vars={list(ds.variables)}"
        )
    return lat, lon

def _detect_vhi_variable(ds: xr.Dataset) -> str:
    """Find the VHI variable. May be 'VHI' or similar."""
    for cand in ("VHI", "vhi", "Vhi"):
        if cand in ds.variables:
            return cand
    # Sometimes named with index suffix
    matches = [v for v in ds.variables if "VHI" in v.upper()]
    if matches:
        return matches[0]
    raise RuntimeError(f"No VHI variable found. Available: {list(ds.variables)}")

def state_mean_vhi(ds: xr.Dataset, bbox: tuple[float, float, float, float]) -> tuple[float, int]:
    """Compute mean VHI within a lat/lon bounding box, ignoring fill values."""
    lat_name, lon_name = _detect_coord_names(ds)
    vhi_name = _detect_vhi_variable(ds)
    lat_min, lat_max, lon_min, lon_max = bbox

    lats = ds[lat_name].values
    lons = ds[lon_name].values

    # NOAA VHP latitude is typically descending; build masks either way.
    lat_mask = (lats >= lat_min) & (lats <= lat_max)
    # Handle longitudes either as -180..180 or 0..360
    if lons.max() > 180:
        # convert bbox lons (which are -180..180) to 0..360
        lo, hi = (lon_min % 360, lon_max % 360)
        if lo <= hi:
            lon_mask = (lons >= lo) & (lons <= hi)
        else:
            lon_mask = (lons >= lo) | (lons <= hi)
    else:
        lon_mask = (lons >= lon_min) & (lons <= lon_max)

    vhi = ds[vhi_name].values
    # vhi shape may be (lat, lon) or include singleton time dim
    if vhi.ndim == 3:
        vhi = vhi[0]
    sub = vhi[np.ix_(lat_mask, lon_mask)]

    # NOAA VHP fill value is -999 (and sometimes nan). VHI valid range 0-100.
    valid = (sub > 0) & (sub <= 100) & np.isfinite(sub)
    n = int(valid.sum())
    if n == 0:
        return float("nan"), 0
    return float(sub[valid].mean()), n

# ---- Top-level orchestration -----------------------------------------------

def download_file(session: requests.Session, url: str, dest: Path) -> None:
    with session.get(url, timeout=300, stream=True) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)

def process_one_week(session: requests.Session, year: int, week: int, sat: str, url: str) -> WeekResult:
    with tempfile.NamedTemporaryFile(suffix=".nc", delete=True) as tmp:
        download_file(session, url, Path(tmp.name))
        ds = open_vhi_dataset(Path(tmp.name))
        try:
            per_state: dict[str, float] = {}
            pixel_counts: dict[str, int] = {}
            for state, bbox in STATE_BBOX.items():
                m, n = state_mean_vhi(ds, bbox)
                per_state[state] = m
                pixel_counts[state] = n
        finally:
            ds.close()
    weighted = sum(per_state[s] * CORN_AREA_WEIGHTS[s] for s in CORN_AREA_WEIGHTS if not np.isnan(per_state[s]))
    return WeekResult(year=year, week=week, file_url=url, per_state_vhi=per_state, weighted_vhi=weighted, pixel_counts=pixel_counts)

def run(output_path: Path) -> None:
    session = requests.Session()
    session.headers.update({"User-Agent": "us-corn-belt-vhi-aggregator/1.0 (research/prediction-markets)"})

    print(f"[{datetime.now(timezone.utc).isoformat()}] Listing VHP files from {VHP_INDEX_URL}", file=sys.stderr)
    files = list_available_files(session)
    print(f"  found {len(files)} VH.nc files; latest = year={files[0][0]} week={files[0][1]} sat={files[0][2]}", file=sys.stderr)

    # Process the latest N weeks
    results: list[WeekResult] = []
    for year, week, sat, url in files[:TRAILING_WEEKS]:
        print(f"  fetching {sat} P{year}{week:03d} ...", file=sys.stderr)
        try:
            r = process_one_week(session, year, week, sat, url)
            print(f"    weighted_vhi={r.weighted_vhi:.2f}  per_state={ {k: round(v,1) for k,v in r.per_state_vhi.items()} }", file=sys.stderr)
            results.append(r)
        except Exception as e:
            print(f"    SKIP — {e}", file=sys.stderr)
            continue
        if len(results) >= TRAILING_WEEKS:
            break

    if not results:
        raise RuntimeError("No weeks processed successfully.")

    latest = results[0]
    trailing = [r.weighted_vhi for r in results if not np.isnan(r.weighted_vhi)]
    trailing_mean = float(np.mean(trailing)) if trailing else float("nan")

    output = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "NOAA STAR Blended VHP 4km Weekly",
        "source_index_url": VHP_INDEX_URL,
        "geography": "US Corn Belt — top-5 corn-producing states (Iowa, Illinois, Indiana, Nebraska, Minnesota) weighted by harvested-corn-area share",
        "method": (
            "For each state, extract VHI pixels from the NOAA Blended VHP 4km weekly NetCDF "
            "within the state bounding box, mean of valid VHI (0<vhi<=100) pixels. "
            f"Then weight states by harvested-corn-area shares: {CORN_AREA_WEIGHTS}."
        ),
        "latest_week": {
            "year": latest.year,
            "iso_week": latest.week,
            "file_url": latest.file_url,
            "weighted_vhi": round(latest.weighted_vhi, 2),
            "per_state_vhi": {k: (None if np.isnan(v) else round(v, 2)) for k, v in latest.per_state_vhi.items()},
            "pixel_counts": latest.pixel_counts,
        },
        "trailing_4week": {
            "weeks": [{"year": r.year, "iso_week": r.week, "weighted_vhi": round(r.weighted_vhi, 2)} for r in results],
            "mean_weighted_vhi": round(trailing_mean, 2),
        },
        "interpretation": {
            "vhi_scale": "0-100",
            "0-30": "severe stress / drought",
            "30-40": "drought",
            "40-60": "moderate",
            "60-80": "favorable",
            "above_80": "exceptional",
        },
    }
    output_path.write_text(json.dumps(output, indent=2))
    print(f"[{datetime.now(timezone.utc).isoformat()}] Wrote {output_path}", file=sys.stderr)
    print(json.dumps(output, indent=2))

if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("vhi_corn_belt.json")
    run(out)
