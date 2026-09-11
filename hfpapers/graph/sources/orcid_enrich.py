#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ORCID API enrichment — fetch employment/education affiliations.

Pipeline:
  1. Scan graph for PERSON nodes with ``orcid`` attribute
  2. Query ORCID public API (free, no key) for employments + educations
  3. Cache to JSONL (``~/.hermes/orcid_cache.jsonl``)
  4. Extract unique institution names with ORCID-provided addresses
  5. Add INSTITUTION / CITY / COUNTRY nodes + AFFILIATED_WITH edges
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

import requests

ORCID_API = "https://pub.orcid.org/v3.0"
DEFAULT_CACHE = "~/.hermes/orcid_cache.jsonl"
DELAY_SECONDS = 1.5  # ORCID public API: 1 req/s, 1.5 to be safe

logger = logging.getLogger("hfpapers.graph.orcid_enrich")


# ═══════════════════════════════════════════════════════════════
# 1. ORCID API — fetch employment + education records
# ═══════════════════════════════════════════════════════════════

def fetch_one(orcid: str) -> list[dict]:
    """Fetch employment and education affiliations for one ORCID.

    Args:
        orcid: 16-character ORCID iD (e.g. 0000-0002-1825-0097).

    Returns:
        List of affiliation dicts, each containing
        ``organization``, ``address``, ``department-name``, ``role-title``.
        Empty list on any error.
    """
    results: list[dict] = []
    for endpoint in ("employments", "educations"):
        url = f"{ORCID_API}/{orcid}/{endpoint}"
        try:
            resp = requests.get(url, headers={"Accept": "application/json"}, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            logger.warning("ORCID %s/%s failed: %s", orcid, endpoint, e)
            continue
        except json.JSONDecodeError as e:
            logger.warning("ORCID %s/%s bad JSON: %s", orcid, endpoint, e)
            continue

        groups = data.get("affiliation-group", [])
        for group in groups:
            for summary in group.get("summaries", []):
                key = f"{endpoint.rstrip('s')}-summary"  # employment-summary or education-summary
                affil = summary.get(key)
                if not affil:
                    continue
                org = affil.get("organization") or {}
                addr = org.get("address") or {}
                disambig = org.get("disambiguated-organization") or {}
                results.append({
                    "orcid": orcid,
                    "source_endpoint": endpoint,
                    "organization_name": (org.get("name") or "").strip(),
                    "city": (addr.get("city") or "").strip(),
                    "region": (addr.get("region") or "").strip(),
                    "country": (addr.get("country") or "").strip(),
                    "ror": (disambig.get("disambiguated-organization-identifier") or "").strip(),
                    "department": (affil.get("department-name") or "").strip(),
                    "role": (affil.get("role-title") or "").strip(),
                    "start_year": _extract_year(affil, "start-date"),
                    "end_year": _extract_year(affil, "end-date"),
                })
    return results


def _extract_year(affil: dict, key: str) -> str:
    """Extract year from ORCID date object (e.g. ``{'year': {'value': '2025'}}``)."""
    date_obj = affil.get(key) or {}
    year_obj = date_obj.get("year") or {}
    return str(year_obj.get("value", ""))


# ═══════════════════════════════════════════════════════════════
# 2. JSONL Cache
# ═══════════════════════════════════════════════════════════════

class OrcidCache:
    """JSONL-based ORCID API result cache.

    Format (one JSON object per line)::

        {"orcid":"0000-0002-1825-0097","organization_name":"Example University",
         "city":"New York","country":"US","role":"Courant Instructor",
         "source_endpoint":"employments","fetched_at":1756215811}
    """

    def __init__(self, path: str = DEFAULT_CACHE):
        self._path = Path(path).expanduser()
        self._cache: dict[str, list[dict]] = {}
        self._load()

    def _load(self):
        """Load cache into memory, grouped by ORCID."""
        if not self._path.exists():
            self._cache = {}
            return
        for line in self._path.read_text(encoding="utf-8").strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                o = record.get("orcid", "")
                if o:
                    self._cache.setdefault(o, []).append(record)
            except (json.JSONDecodeError, KeyError):
                continue

    def lookup(self, orcid: str) -> Optional[list[dict]]:
        """Return cached records for an ORCID, or None if not cached."""
        return self._cache.get(orcid)

    def save(self, records: list[dict]):
        """Append multiple records to the cache file."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as f:
            for r in records:
                r["fetched_at"] = int(time.time())
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        # Also update in-memory cache
        for r in records:
            o = r.get("orcid", "")
            if o:
                self._cache.setdefault(o, []).append(r)

    @property
    def count(self) -> int:
        """Total cached affiliation records."""
        return sum(len(v) for v in self._cache.values())

    @property
    def orcid_count(self) -> int:
        """Number of unique ORCIDs in cache."""
        return len(self._cache)


# ═══════════════════════════════════════════════════════════════
# 3. Batch fetch from graph
# ═══════════════════════════════════════════════════════════════

def extract_orcids_from_graph(G: "nx.Graph") -> dict[str, str]:  # noqa: N803,F821
    """Scan graph for PERSON nodes with ``orcid`` attributes.

    Args:
        G: NetworkX graph.

    Returns:
        Dict mapping ``orcid`` → ``person_node_id``.
    """
    result: dict[str, str] = {}
    for nid, attrs in G.nodes(data=True):
        node_type = attrs.get("type")
        if node_type is None or getattr(node_type, "name", "") != "PERSON":
            continue
        orcid = (attrs.get("orcid") or "").strip()
        if not orcid:
            continue
        # Normalize: strip URI prefix, whitespace
        orcid = orcid.replace("https://orcid.org/", "").replace("http://orcid.org/", "").strip()
        if orcid and orcid != "0000-0000-0000-0000":
            result[orcid] = nid
    return result


def batch_fetch(
    orcid_to_person: dict[str, str],
    cache_path: str = DEFAULT_CACHE,
    force: bool = False,
) -> dict[str, list[dict]]:
    """Fetch ORCID affiliations for a batch, respecting cache.

    Args:
        orcid_to_person: Dict mapping ORCID → person_node_id.
        cache_path: Path to JSONL cache file.
        force: If True, re-fetch even cached ORCIDs.

    Returns:
        Dict mapping ``orcid`` → list of affiliation dicts.
    """
    cache = OrcidCache(cache_path)
    results: dict[str, list[dict]] = {}

    for i, (orcid, pid) in enumerate(sorted(orcid_to_person.items())):
        # Check cache first
        cached = cache.lookup(orcid) if not force else None
        if cached is not None:
            logger.debug("[%d/%d] %s: %d cached records", i + 1, len(orcid_to_person), orcid, len(cached))
            results[orcid] = cached
            continue

        # Fetch from API
        logger.info("[%d/%d] Fetching ORCID %s (%s)...", i + 1, len(orcid_to_person), orcid, pid)
        records = fetch_one(orcid)
        if records:
            cache.save(records)
            results[orcid] = records
            logger.info("  → %d affiliation(s) saved", len(records))
        else:
            # Save empty marker so we don't re-fetch
            cache.save([{"orcid": orcid, "source_endpoint": "empty", "organization_name": "",
                         "city": "", "region": "", "country": "", "ror": "",
                         "department": "", "role": ""}])
            results[orcid] = []
            logger.info("  → no affiliations found")

        # Rate limit
        if i < len(orcid_to_person) - 1:
            time.sleep(DELAY_SECONDS)

    return results


# ═══════════════════════════════════════════════════════════════
# 4. Enrich graph with ORCID-derived institutions
# ═══════════════════════════════════════════════════════════════

def enrich_graph_from_orcid(
    G: "nx.Graph",  # noqa: N803,F821
    orcid_results: dict[str, list[dict]],
    orcid_to_person: dict[str, str],
    geo_cache_path: str = "~/.hermes/geo_cache.jsonl",
) -> dict[str, int]:
    """Add INSTITUTION / CITY / COUNTRY nodes + edges from ORCID data.

    Args:
        G: NetworkX graph (mutated in-place).
        orcid_results: Output from ``batch_fetch()``.
        orcid_to_person: Dict mapping ``orcid`` → ``person_node_id``.
        geo_cache_path: Path to geo cache for institution geocoding.

    Returns:
        Stats dict with node/edge counts.
    """
    from hfpapers.graph.schema import EdgeType, NodeType, node_id
    from hfpapers.graph.sources.institutions import (
        GeoCache,
        _city_node_id,
        institution_abbrev,
    )

    # Register any new institutions into the geo cache so they get lat/lng
    geo_cache = GeoCache(geo_cache_path)

    # ── Step 1: Collect unique institutions from ORCID data ──
    institutions: dict[str, dict] = {}
    orcid_person_to_insts: dict[str, set[str]] = {}

    for orcid, records in orcid_results.items():
        pid = orcid_to_person.get(orcid, "")
        orcid_person_to_insts.setdefault(pid, set())

        for rec in records:
            org_name = rec.get("organization_name", "").strip()
            if not org_name:
                continue
            if org_name not in institutions:
                # Try to get geo from cache or curated dict
                geo = _resolve_institution_geo(org_name, rec, geo_cache)
                institutions[org_name] = geo
            orcid_person_to_insts[pid].add(org_name)

    # ── Step 2: Add nodes ──
    added_nodes = 0
    countries_seen: set[str] = set()
    cities_seen: set[str] = set()

    for org_name, geo in institutions.items():
        country = geo.get("country", "")
        city = geo.get("city", "")
        lat = geo.get("lat", 0.0) or 0.0
        lng = geo.get("lng", 0.0) or 0.0

        # Use ORCID's canonical name if available, else raw org name
        canonical_name = geo.get("canonical", org_name)[:80] or org_name[:80]
        inst_id = node_id(NodeType.INSTITUTION, canonical_name)

        if inst_id not in G:
            G.add_node(
                inst_id,
                type=NodeType.INSTITUTION,
                label=canonical_name,
                abbrev=institution_abbrev(canonical_name),
                color="#c084fc",
                size=12,
                lat=lat,
                lng=lng,
                geo_source=geo.get("source", "orcid"),
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
                    lat=lat,
                    lng=lng,
                )
                added_nodes += 1
            cities_seen.add(cid)

            # LOCATED_IN: institution → city
            if not G.has_edge(inst_id, cid):
                G.add_edge(inst_id, cid, type=EdgeType.LOCATED_IN)
            # LOCATED_IN: city → country
            if not G.has_edge(cid, country_id):
                G.add_edge(cid, country_id, type=EdgeType.LOCATED_IN)

    # ── Step 3: Add AFFILIATED_WITH edges ──
    edge_count = 0
    for pid, org_names in orcid_person_to_insts.items():
        if not G.has_node(pid):
            continue
        for org_name in org_names:
            geo = institutions.get(org_name, {})
            canonical_name = geo.get("canonical", org_name)[:80] or org_name[:80]
            inst_id = node_id(NodeType.INSTITUTION, canonical_name)
            if G.has_node(inst_id) and not G.has_edge(pid, inst_id):
                G.add_edge(pid, inst_id, type=EdgeType.AFFILIATED_WITH, source="orcid")
                edge_count += 1

    logger.info(
        "ORCID enrichment: +%d nodes, %d AFFILIATED_WITH edges",
        added_nodes, edge_count,
    )
    return {"added_nodes": added_nodes, "added_edges": edge_count}


def _resolve_institution_geo(
    org_name: str,
    orcid_record: dict,
    geo_cache: "GeoCache",  # noqa: F821
) -> dict:
    """Resolve geo data for an ORCID organization.

    Priority:
      1. Curated dict (``INSTITUTION_CITY`` in ``institutions.py``)
      2. ORCID-provided address (city, country)
      3. Existing geo cache

    Returns geo dict with ``canonical``, ``city``, ``country``, ``lat``, ``lng``, ``source``.
    """
    from hfpapers.graph.sources.institutions import CURATED_LOOKUP, _norm_key

    # 1. Curated dict
    normed = _norm_key(org_name)
    if normed in CURATED_LOOKUP:
        entry = CURATED_LOOKUP[normed]
        return {
            "canonical": entry.get("canonical", org_name),
            "city": entry.get("city", ""),
            "country": entry.get("country", ""),
            "lat": entry.get("lat", 0.0),
            "lng": entry.get("lng", 0.0),
            "source": "curated",
        }

    # 2. Geo cache
    cached = geo_cache.lookup(org_name)
    if cached:
        return cached

    # 3. ORCID-provided address — assign centroid of country/city
    city = orcid_record.get("city", "")
    region = orcid_record.get("region", "")
    country = _country_name(orcid_record.get("country", ""))
    lat, lng = _city_centroid(city, country)

    return {
        "canonical": org_name,
        "city": city or region,
        "country": country,
        "lat": lat,
        "lng": lng,
        "source": "orcid",
    }


# ═══════════════════════════════════════════════════════════════
# 5. Country / city centroid helpers
# ═══════════════════════════════════════════════════════════════

_COUNTRY_NAMES = {
    "US": "USA",
    "USA": "USA",
    "United States": "USA",
    "CN": "China",
    "China": "China",
    "GB": "UK",
    "UK": "UK",
    "SG": "Singapore",
    "CH": "Switzerland",
    "DE": "Germany",
    "FR": "France",
    "JP": "Japan",
}

# Known institution centroids (lat, lng)
_KNOWN_CENTROIDS: dict[str, tuple[float, float]] = {
    # USA
    "New York": (40.7128, -74.0060),
    "Princeton": (40.3431, -74.6551),
    "Cambridge, MA": (42.3601, -71.0942),  # Cambridge, MA (MIT/Harvard)
    "Stanford": (37.4275, -122.1697),
    "Palo Alto": (37.4419, -122.1430),
    "San Francisco": (37.7749, -122.4194),
    "Los Angeles": (34.0522, -118.2437),
    "Chicago": (41.8781, -87.6298),
    "Berkeley": (37.8716, -122.2727),
    "Seattle": (47.6062, -122.3321),
    "Boston": (42.3601, -71.0589),
    "Houston": (29.7604, -95.3698),
    "New Haven": (41.3083, -72.9282),
    # China
    "Beijing": (39.9042, 116.4074),
    "Shanghai": (31.2304, 121.4737),
    "Hefei": (31.8206, 117.2272),
    "Hangzhou": (30.2741, 120.1551),
    "Nanjing": (32.0603, 118.7969),
    "Changsha": (28.2282, 112.9388),
    "Shenzhen": (22.5431, 114.0579),
    "Guangzhou": (23.1291, 113.2644),
    "Wuhan": (30.5928, 114.3055),
    "Chengdu": (30.5728, 104.0668),
    "Xi'an": (34.3416, 108.9398),
    # Europe
    "Zurich": (47.3769, 8.5417),
    "Paris": (48.8566, 2.3522),
    "Munich": (48.1351, 11.5820),
    "Oxford": (51.7520, -1.2577),
    "Cambridge": (52.2053, 0.1218),  # UK Cambridge
    "London": (51.5074, -0.1278),
    "Berlin": (52.5200, 13.4050),
    # Asia
    "Singapore": (1.3521, 103.8198),
    "Tokyo": (35.6762, 139.6503),
    "Seoul": (37.5665, 126.9780),
}


def _city_centroid(city: str, country: str) -> tuple[float, float]:
    """Get estimated centroid for a city. Falls back to country centroid."""
    if not city:
        return _country_centroid(country)
    key = city.strip()
    if key in _KNOWN_CENTROIDS:
        return _KNOWN_CENTROIDS[key]

    # Try city + country combo
    combo = f"{key}, {country}" if country else key
    if combo in _KNOWN_CENTROIDS:
        return _KNOWN_CENTROIDS[combo]

    return _country_centroid(country)


_COUNTRY_CENTROIDS = {
    "USA": (39.8283, -98.5795),
    "China": (35.8617, 104.1954),
    "UK": (55.3781, -3.4360),
    "Singapore": (1.3521, 103.8198),
    "Switzerland": (46.8182, 8.2275),
    "Germany": (51.1657, 10.4515),
    "France": (46.6034, 1.8883),
    "Japan": (36.2048, 138.2529),
    "Canada": (56.1304, -106.3468),
    "Australia": (-25.2744, 133.7751),
    "South Korea": (35.9078, 127.7669),
    "India": (20.5937, 78.9629),
    "Netherlands": (52.1326, 5.2913),
    "Italy": (41.8719, 12.5674),
}


def _country_centroid(country: str) -> tuple[float, float]:
    """Get estimated centroid for a country."""
    return _COUNTRY_CENTROIDS.get(country, (0.0, 0.0))


def _country_name(code_or_name: str) -> str:
    """Normalize country code/name to canonical form."""
    code = code_or_name.strip().upper()
    if code in _COUNTRY_NAMES:
        return _COUNTRY_NAMES[code]
    # Return as-is if it's already a full name
    if len(code) > 3:
        return code_or_name.strip()
    return code_or_name.strip()
