#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Institution geo-resolver — extract affiliations, geocode, cache.

Three-tier resolution (in order):
  1. Curated mapping (``INSTITUTION_CITY``) — zero-API, high quality
  2. JSONL cache (``~/.hermes/geo_cache.jsonl``) — previously geocoded results
  3. Nominatim API (optional) — OpenStreetMap geocoding, 1 req/s rate limit

Usage::

    from hfpapers.graph.sources.institutions import (
        extract_institutions,
        geocode_institutions,
        enrich_graph,
        GeoCache,
    )

    # Phase 5 in build()
    inst_names = extract_institutions(wiki_persons)
    geo_data = geocode_institutions(inst_names)
    enrich_graph(G, geo_data)
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

from hfpapers.graph.schema import (
    EdgeType,
    NodeType,
    KG_VERSION,
    node_id,
)

logger = logging.getLogger("hfpapers.graph.institutions")

# ── Default cache path ─────────────────────────────────────────
DEFAULT_CACHE = "~/.hermes/geo_cache.jsonl"


# ═══════════════════════════════════════════════════════════════
# 1. Curated institution → city/country mapping
# ═══════════════════════════════════════════════════════════════

INSTITUTION_CITY: dict[str, dict] = {
    # ── USTC & affiliates (core cluster) ──
    "中国科学技术大学": {
        "canonical": "University of Science and Technology of China",
        "city": "Hefei", "country": "China",
        "lat": 31.8195, "lng": 117.2497,
    },
    "ustc": {
        "canonical": "University of Science and Technology of China",
        "city": "Hefei", "country": "China",
        "lat": 31.8195, "lng": 117.2497,
    },
    "university of science and technology of china": {
        "canonical": "University of Science and Technology of China",
        "city": "Hefei", "country": "China",
        "lat": 31.8195, "lng": 117.2497,
    },
    "中科院量子信息重点实验室": {
        "canonical": "CAS Key Lab of Quantum Information",
        "city": "Hefei", "country": "China",
        "lat": 31.8195, "lng": 117.2497,
    },
    "chinese academy of sciences": {
        "canonical": "Chinese Academy of Sciences",
        "city": "Beijing", "country": "China",
        "lat": 39.9054, "lng": 116.3912,
    },
    "中国科学院": {
        "canonical": "Chinese Academy of Sciences",
        "city": "Beijing", "country": "China",
        "lat": 39.9054, "lng": 116.3912,
    },
    "university of chinese academy of sciences": {
        "canonical": "University of Chinese Academy of Sciences",
        "city": "Beijing", "country": "China",
        "lat": 39.9075, "lng": 116.3343,
    },
    # ── PKU ──
    "北京大学": {
        "canonical": "Peking University",
        "city": "Beijing", "country": "China",
        "lat": 39.9856, "lng": 116.3059,
    },
    "peking university": {
        "canonical": "Peking University",
        "city": "Beijing", "country": "China",
        "lat": 39.9856, "lng": 116.3059,
    },
    # ── Zhejiang ──
    "zhejiang lab": {
        "canonical": "Zhejiang Lab",
        "city": "Hangzhou", "country": "China",
        "lat": 30.2729, "lng": 120.1709,
    },
    "zhejiang university": {
        "canonical": "Zhejiang University",
        "city": "Hangzhou", "country": "China",
        "lat": 30.2735, "lng": 120.1217,
    },
    # ── Other Chinese universities ──
    "上海交通大学": {
        "canonical": "Shanghai Jiao Tong University",
        "city": "Shanghai", "country": "China",
        "lat": 31.0250, "lng": 121.4347,
    },
    "shanghai jiao tong university": {
        "canonical": "Shanghai Jiao Tong University",
        "city": "Shanghai", "country": "China",
        "lat": 31.0250, "lng": 121.4347,
    },
    "tsinghua university": {
        "canonical": "Tsinghua University",
        "city": "Beijing", "country": "China",
        "lat": 39.9958, "lng": 116.3273,
    },
    "清华大学": {
        "canonical": "Tsinghua University",
        "city": "Beijing", "country": "China",
        "lat": 39.9958, "lng": 116.3273,
    },
    "nanjing university": {
        "canonical": "Nanjing University",
        "city": "Nanjing", "country": "China",
        "lat": 32.0584, "lng": 118.7510,
    },
    "fudan university": {
        "canonical": "Fudan University",
        "city": "Shanghai", "country": "China",
        "lat": 31.2957, "lng": 121.5108,
    },
    # ── International ──
    "nanyang technological university": {
        "canonical": "Nanyang Technological University",
        "city": "Singapore", "country": "Singapore",
        "lat": 1.3483, "lng": 103.6831,
    },
    "ntu": {
        "canonical": "Nanyang Technological University",
        "city": "Singapore", "country": "Singapore",
        "lat": 1.3483, "lng": 103.6831,
    },
    "national university of singapore": {
        "canonical": "National University of Singapore",
        "city": "Singapore", "country": "Singapore",
        "lat": 1.2966, "lng": 103.7764,
    },
    "eth zurich": {
        "canonical": "ETH Zurich",
        "city": "Zurich", "country": "Switzerland",
        "lat": 47.3769, "lng": 8.5497,
    },
    "mit": {
        "canonical": "Massachusetts Institute of Technology",
        "city": "Cambridge", "country": "USA",
        "lat": 42.3601, "lng": -71.0942,
    },
    "massachusetts institute of technology": {
        "canonical": "Massachusetts Institute of Technology",
        "city": "Cambridge", "country": "USA",
        "lat": 42.3601, "lng": -71.0942,
    },
    "stanford university": {
        "canonical": "Stanford University",
        "city": "Stanford", "country": "USA",
        "lat": 37.4275, "lng": -122.1697,
    },
    "oxford university": {
        "canonical": "University of Oxford",
        "city": "Oxford", "country": "UK",
        "lat": 51.7548, "lng": -1.2544,
    },
    "cambridge university": {
        "canonical": "University of Cambridge",
        "city": "Cambridge", "country": "UK",
        "lat": 52.2053, "lng": 0.1218,
    },
    "princeton university": {
        "canonical": "Princeton University",
        "city": "Princeton", "country": "USA",
        "lat": 40.3431, "lng": -74.6551,
    },
    "nyu": {
        "canonical": "New York University",
        "city": "New York", "country": "USA",
        "lat": 40.7295, "lng": -73.9965,
    },
    "new york university": {
        "canonical": "New York University",
        "city": "New York", "country": "USA",
        "lat": 40.7295, "lng": -73.9965,
    },
    # ── Research institutes ──
    "pppl": {
        "canonical": "Princeton Plasma Physics Laboratory",
        "city": "Princeton", "country": "USA",
        "lat": 40.3402, "lng": -74.6484,
    },
    "princeton plasma physics laboratory": {
        "canonical": "Princeton Plasma Physics Laboratory",
        "city": "Princeton", "country": "USA",
        "lat": 40.3402, "lng": -74.6484,
    },
    "courant institute": {
        "canonical": "Courant Institute of Mathematical Sciences",
        "city": "New York", "country": "USA",
        "lat": 40.7295, "lng": -73.9965,
    },
    "hunan university": {
        "canonical": "Hunan University",
        "city": "Changsha", "country": "China",
        "lat": 28.1869, "lng": 112.9414,
    },
    "湖南大学": {
        "canonical": "Hunan University",
        "city": "Changsha", "country": "China",
        "lat": 28.1869, "lng": 112.9414,
    },
    "ecnu": {
        "canonical": "East China Normal University",
        "city": "Shanghai", "country": "China",
        "lat": 31.2251, "lng": 121.3993,
    },
    "east china normal university": {
        "canonical": "East China Normal University",
        "city": "Shanghai", "country": "China",
        "lat": 31.2251, "lng": 121.3993,
    },
    "sorbonne universite": {
        "canonical": "Sorbonne University",
        "city": "Paris", "country": "France",
        "lat": 48.8493, "lng": 2.3574,
    },
    "max planck institute": {
        "canonical": "Max Planck Institute",
        "city": "Munich", "country": "Germany",
        "lat": 48.1479, "lng": 11.5676,
    },
    "university of tokyo": {
        "canonical": "University of Tokyo",
        "city": "Tokyo", "country": "Japan",
        "lat": 35.7123, "lng": 139.7780,
    },
}

# ── Build lookup key variants for curated dict ──────────────────
# Normalize: lowercase, strip punctuation, collapse whitespace
def _norm_key(name: str) -> str:
    """Normalize an institution name for curated-dict lookup."""
    n = name.lower().strip()
    n = re.sub(r"[^a-z0-9\u4e00-\u9fff\s]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


CURATED_LOOKUP = {_norm_key(k): v for k, v in INSTITUTION_CITY.items()}


# ═══════════════════════════════════════════════════════════════
# 2. JSONL geo cache
# ═══════════════════════════════════════════════════════════════

class GeoCache:
    """JSONL-based geo-coding cache.

    Format (one JSON object per line)::

        {"institution":"ustc","canonical":"University of Science and Technology of China",
         "city":"Hefei","country":"China","lat":31.8195,"lng":117.2497,
         "source":"curated","version":"0.10.3"}

    Methods:
        lookup(name): return cached geo dict or None
        save(record): append one record to the cache file
        load_all(): iterate all cached records
    """

    def __init__(self, path: str = DEFAULT_CACHE):
        self._path = Path(path).expanduser()
        self._cache: dict[str, dict] = {}
        self._dirty = False
        self._load()

    def _load(self):
        """Load all cached records into memory dict."""
        if not self._path.exists():
            self._cache = {}
            return
        for line in self._path.read_text(encoding="utf-8").strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                key = _norm_key(record.get("institution", ""))
                if key:
                    self._cache[key] = record
            except (json.JSONDecodeError, KeyError):
                continue

    def lookup(self, name: str) -> Optional[dict]:
        """Look up a cached geo record by institution name.

        Returns:
            Geo dict with keys: canonical, city, country, lat, lng, source.
            None if not found in cache.
        """
        key = _norm_key(name)
        return self._cache.get(key)

    def save(self, record: dict):
        """Append one geo record to the cache file."""
        record.setdefault("version", KG_VERSION)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        key = _norm_key(record.get("institution", ""))
        self._cache[key] = record

    def load_all(self) -> list[dict]:
        """Iterate all cached records."""
        return list(self._cache.values())

    @property
    def count(self) -> int:
        return len(self._cache)


# ═══════════════════════════════════════════════════════════════
# 3. Institution name extraction
# ═══════════════════════════════════════════════════════════════

def extract_institutions(wiki_persons: dict[str, dict]) -> list[str]:
    """Extract unique institution names from wiki/people affiliation fields.

    Splits multi-affiliation strings on `` · `` (Chinese middle dot) or ``;``.

    Returns:
        Sorted list of unique institution name strings.
    """
    names: set[str] = set()
    for pid, attrs in wiki_persons.items():
        affil = (attrs.get("affiliation") or "").strip()
        if not affil:
            continue
        # Split on Chinese middle dot or semicolon
        parts = re.split(r"\s*[·;]\s*", affil)
        for part in parts:
            part = part.strip()
            if part and len(part) > 2:
                # Normalize: "中国科学技术大学 · 物理学院" → "中国科学技术大学"
                # Take the first segment before any sub-unit indicator
                # (handles both Chinese and English formats)
                names.add(part)
    return sorted(names)


# ═══════════════════════════════════════════════════════════════
# 4. Geocode resolution
# ═══════════════════════════════════════════════════════════════

def _resolve_one(
    name: str,
    cache: GeoCache,
    use_api: bool = False,
) -> Optional[dict]:
    """Resolve one institution name to geo data.

    Priority:
      1. Curated dict lookup (zero-API)
      2. JSONL cache (previously geocoded)
      3. Nominatim API via geopy (if enabled)

    Returns:
        Geo dict or None if unresolvable.
    """
    normed = _norm_key(name)

    # 1. Curated dict
    if normed in CURATED_LOOKUP:
        entry = CURATED_LOOKUP[normed]
        record = {
            "institution": _canonical_name(entry["canonical"]),
            "canonical": entry["canonical"],
            "city": entry["city"],
            "country": entry["country"],
            "lat": entry["lat"],
            "lng": entry["lng"],
            "source": "curated",
        }
        if not cache.lookup(name):
            cache.save(record)
        return record

    # 2. JSONL cache
    cached = cache.lookup(name)
    if cached:
        return cached
    cached = cache.lookup(_norm_key(name))
    if cached:
        return cached

    # 3. Nominatim via geopy
    if use_api:
        return _query_nominatim_geopy(name, cache)

    return None


def _canonical_name(name: str) -> str:
    """Generate a slug-like key for an institution."""
    return name.lower().strip().replace(" ", "-")


# ── Nominatim via geopy ─────────────────────────────────────────

_NOMINATIM: object | None = None
_NOMINATIM_RATE_LIMITED: object | None = None


def _query_nominatim_geopy(name: str, cache: GeoCache) -> Optional[dict]:
    """Query Nominatim via geopy with built-in RateLimiter.

    Uses a module-level singleton ``RateLimiter(Nominatim(...).geocode, min_delay_seconds=1)``
    to respect Nominatim's 1 request/second public API policy.
    Result is saved to JSONL cache on success.
    """
    global _NOMINATIM, _NOMINATIM_RATE_LIMITED

    if _NOMINATIM_RATE_LIMITED is None:
        from geopy.extra.rate_limiter import RateLimiter
        from geopy.geocoders import Nominatim

        _NOMINATIM = Nominatim(
            user_agent="hfpclawer/0.10.3 (knowledge-graph-geo-enrichment; mailto:lishen@example.com)",
        )
        _NOMINATIM_RATE_LIMITED = RateLimiter(
            _NOMINATIM.geocode,
            min_delay_seconds=1.0,
            max_retries=2,
            swallow_exceptions=False,
            return_value_on_exception=None,
        )

    try:
        location = _NOMINATIM_RATE_LIMITED(name, exactly_one=True, addressdetails=True)
        if location is None:
            logger.debug("geopy/Nominatim: no results for '%s'", name)
            return None

        address = location.raw.get("address", {}) if location.raw else {}
        record = {
            "institution": _canonical_name(name),
            "canonical": location.address[:120] if location.address else name,
            "city": (address.get("city")
                     or address.get("town")
                     or address.get("village")
                     or address.get("county", "")),
            "country": address.get("country", ""),
            "lat": location.latitude,
            "lng": location.longitude,
            "source": "nominatim",
        }
        cache.save(record)
        logger.debug("geopy/Nominatim: '%s' → %s, %s", name, record["city"], record["country"])
        return record

    except Exception as e:
        logger.warning("geopy/Nominatim query failed for '%s': %s", name, e)
        return None


def geocode_institutions(
    names: list[str],
    cache_path: str = DEFAULT_CACHE,
    use_api: bool = False,
) -> dict[str, dict]:
    """Resolve a list of institution names to geo data.

    Args:
        names: List of institution name strings.
        cache_path: Path to the JSONL geo cache file.
        use_api: If True, query Nominatim for uncached institutions.

    Returns:
        Dict mapping ``institution:slug`` → geo record dict.
    """
    cache = GeoCache(cache_path)
    results: dict[str, dict] = {}

    for name in names:
        record = _resolve_one(name, cache, use_api=use_api)
        if record:
            key = _canonical_name(record.get("canonical", name))
            # Keep the best result (curated > nominatim > unknown)
            if key not in results or record["source"] == "curated":
                results[key] = record
        else:
            logger.debug("Unresolved institution: '%s'", name)
            results[_canonical_name(name)] = {
                "institution": _canonical_name(name),
                "canonical": name,
                "city": "",
                "country": "",
                "lat": 0.0,
                "lng": 0.0,
                "source": "unknown",
            }

    return results


# ═══════════════════════════════════════════════════════════════
# 5. Graph enrichment
# ═══════════════════════════════════════════════════════════════

def _city_node_id(city: str, country: str) -> str:
    """Generate a unique city node ID."""
    key = f"{_norm_key(city)}-{_norm_key(country)}" if country else _norm_key(city)
    return node_id(NodeType.CITY, key)


# ── Institution abbreviation lookup ─────────────────────────────
# Common Chinese university abbreviations, stored as node attribute.
INST_ABBREV: dict[str, str] = {
    "University of Science and Technology of China": "USTC",
    "Peking University": "PKU",
    "Tsinghua University": "THU",
    "Zhejiang University": "ZJU",
    "Shanghai Jiao Tong University": "SJTU",
    "Fudan University": "FDU",
    "Nanjing University": "NJU",
    "Wuhan University": "WHU",
    "Harbin Institute of Technology": "HIT",
    "University of Chinese Academy of Sciences": "UCAS",
    "Sun Yat-sen University": "SYSU",
    "Xi'an Jiaotong University": "XJTU",
    "Nankai University": "NKU",
    "Huazhong University of Science and Technology": "HUST",
    "Beihang University": "BUAA",
    "Tongji University": "TJU",
    "Southeast University": "SEU",
    "Dalian University of Technology": "DLUT",
    "Jilin University": "JLU",
    "Xiamen University": "XMU",
    "Sichuan University": "SCU",
    "Central South University": "CSU",
    "Chongqing University": "CQU",
    "South China University of Technology": "SCUT",
    "Hong Kong University of Science and Technology": "HKUST",
    "University of Hong Kong": "HKU",
    "Chinese University of Hong Kong": "CUHK",
}


def institution_abbrev(name: str) -> str:
    """Return the common abbreviation for a Chinese university, or the name itself."""
    return INST_ABBREV.get(name, name)


def enrich_graph(
    G: "nx.Graph",  # noqa: N802
    geo_data: dict[str, dict],
    wiki_persons: dict[str, dict],
) -> dict[str, int]:
    """Add INSTITUTION / CITY / COUNTRY nodes + edges to graph.

    Args:
        G: NetworkX graph (mutated in-place).
        geo_data: Output from :func:`geocode_institutions`.
        wiki_persons: Dict of wiki person records.

    Returns:
        Stats dict with node/edge counts.
    """
    import networkx as nx  # noqa: N812, F401 — used at runtime via G methods
    added_nodes = 0

    # ── COUNTRY nodes ──
    countries_seen: set[str] = set()
    # ── CITY nodes ──
    cities_seen: set[str] = set()

    for inst_key, geo in geo_data.items():
        country = geo.get("country", "")
        city = geo.get("city", "")
        lat = geo.get("lat", 0.0) or 0.0
        lng = geo.get("lng", 0.0) or 0.0

        # Skip unresolvable institutions (no coords, source=unknown)
        if geo.get("source") == "unknown" or (lat == 0.0 and lng == 0.0):
            continue

        # Institution node (English canonical name)
        canonical_name = geo.get("canonical", inst_key)
        inst_id = node_id(NodeType.INSTITUTION, canonical_name)
        if inst_id not in G:
            G.add_node(
                inst_id,
                type=NodeType.INSTITUTION,
                label=canonical_name[:80],
                abbrev=institution_abbrev(canonical_name),
                color="#c084fc",
                size=12,
                lat=lat,
                lng=lng,
                geo_source=geo.get("source", "unknown"),
            )
            added_nodes += 1

        # Country node
        if country:
            country_id = node_id(NodeType.COUNTRY, country)
            if country_id not in countries_seen and country_id not in G:
                G.add_node(
                    country_id,
                    type=NodeType.COUNTRY,
                    label=country,
                    color="#fb923c",
                    size=8,
                )
                added_nodes += 1
            countries_seen.add(country_id)

        # City node
        if city and country:
            cid = _city_node_id(city, country)
            if cid not in cities_seen and cid not in G:
                G.add_node(
                    cid,
                    type=NodeType.CITY,
                    label=f"{city}, {country}"[:60],
                    color="#f472b6",
                    size=7,
                    lat=geo.get("lat", 0.0),
                    lng=geo.get("lng", 0.0),
                )
                added_nodes += 1
            cities_seen.add(cid)

            # LOCATED_IN: institution → city
            if not G.has_edge(inst_id, cid):
                G.add_edge(inst_id, cid, type=EdgeType.LOCATED_IN)

            # LOCATED_IN: city → country
            if not G.has_edge(cid, country_id):
                G.add_edge(cid, country_id, type=EdgeType.LOCATED_IN)

    # ── AFFILIATED_WITH: wiki-known persons → institutions ──
    for pid, attrs in wiki_persons.items():
        affil = (attrs.get("affiliation") or "").strip()
        if not affil:
            continue
        parts = re.split(r"\s*[·;]\s*", affil)
        for part in parts:
            part = part.strip()
            if not part or len(part) <= 2:
                continue
            # Find best matching institution
            best_inst = None
            for inst_key, geo in geo_data.items():
                canonical = (geo.get("canonical") or "").lower()
                part_lower = part.lower()
                # Match if canonical contains part or vice versa
                if canonical and (canonical in part_lower or part_lower in canonical):
                    best_inst = inst_key
                    break
                # Also check via curated lookup (for Chinese names)
                normed_part = _norm_key(part) if not best_inst else ""
                if normed_part and normed_part in CURATED_LOOKUP:
                    curated_canonical = CURATED_LOOKUP[normed_part]["canonical"].lower()
                    ck = _canonical_name(curated_canonical)
                    if ck in geo_data:
                        best_inst = ck
                        break
            if not best_inst:
                continue
            inst_id = node_id(NodeType.INSTITUTION,
                              geo_data[best_inst].get("canonical", best_inst))
            if G.has_node(pid) and G.has_node(inst_id):
                if not G.has_edge(pid, inst_id):
                    G.add_edge(pid, inst_id, type=EdgeType.AFFILIATED_WITH,
                               source="wiki_affiliation")

    logger.info(
        "Geo enrichment: +%d nodes (INSTITUTION/CITY/COUNTRY), "
        "%d AFFILIATED_WITH edges",
        added_nodes,
        sum(1 for _, _, d in G.edges(data=True)
            if d.get("type") == EdgeType.AFFILIATED_WITH),
    )
    return added_nodes


# ═══════════════════════════════════════════════════════════════
# 6. CLI helpers
# ═══════════════════════════════════════════════════════════════

def geo_stats(geo_data: dict[str, dict]) -> dict:
    """Compute geo enrichment statistics.

    Returns:
        Dict with: n_institutions, n_cities, n_countries,
        n_curated, n_cached, source_breakdown.
    """
    cities: set[str] = set()
    countries: set[str] = set()
    source_counts: dict[str, int] = {}

    for inst_key, geo in geo_data.items():
        src = geo.get("source", "unknown")
        source_counts[src] = source_counts.get(src, 0) + 1
        country = geo.get("country", "")
        city = geo.get("city", "")
        if country:
            countries.add(country)
        if city:
            cities.add(f"{city}, {country}")

    return {
        "n_institutions": len(geo_data),
        "n_cities": len(cities),
        "n_countries": len(countries),
        "source_breakdown": dict(sorted(source_counts.items(), key=lambda x: -x[1])),
    }
