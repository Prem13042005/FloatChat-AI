"""
src/agents/query_understanding/gazetteer.py

FloatChat Oceanographic Regional Gazetteer.
Provides deterministic resolution of approved named oceanographic regions into approximate
WGS-84 coordinate bounding boxes.

Note:
These bounding boxes represent approximate rectangular query envelopes optimized for
relational filtering and PostGIS spatial indexing. They do not constitute authoritative,
jurisdictional, or dynamic oceanographic water mass boundaries.
"""

import re
from typing import Dict, List, Optional, Tuple
from src.agents.query_understanding.models import SpatialBounds

# Approved approximate bounding boxes for the Arabian Sea basin and subregions
REGIONAL_GAZETTEER: Dict[str, SpatialBounds] = {
    "northern arabian sea": SpatialBounds(
        latitude_min=18.0, latitude_max=24.0, longitude_min=58.0, longitude_max=74.0
    ),
    "central arabian sea": SpatialBounds(
        latitude_min=14.0, latitude_max=18.0, longitude_min=62.0, longitude_max=72.0
    ),
    "southern arabian sea": SpatialBounds(
        latitude_min=8.0, latitude_max=14.0, longitude_min=60.0, longitude_max=75.0
    ),
    "arabian sea": SpatialBounds(
        latitude_min=8.0, latitude_max=24.0, longitude_min=55.0, longitude_max=75.0
    ),
}

# Pre-computed list of (canonical_name, SpatialBounds) sorted by descending string length
# to enforce longest-name precedence (e.g. 'northern arabian sea' matches before 'arabian sea').
_GAZETTEER_ORDERED: List[Tuple[str, SpatialBounds]] = sorted(
    REGIONAL_GAZETTEER.items(), key=lambda item: len(item[0]), reverse=True
)


def find_matching_regions(text: str) -> List[Tuple[str, SpatialBounds]]:
    """
    Scans input text case-insensitively and returns all matching gazetteer regions
    in longest-name precedence order without duplicate overlap.

    Args:
        text: Natural language user query string.

    Returns:
        List of tuples: (matched_canonical_name, SpatialBounds).
    """
    if not text:
        return []

    lower_text = text.lower()
    matched: List[Tuple[str, SpatialBounds]] = []
    consumed_spans: List[Tuple[int, int]] = []

    for name, bounds in _GAZETTEER_ORDERED:
        pattern = r"\b" + re.escape(name) + r"\b"
        for m in re.finditer(pattern, lower_text):
            start_idx, end_idx = m.span()
            overlaps = any(
                not (end_idx <= c_start or start_idx >= c_end)
                for c_start, c_end in consumed_spans
            )
            if not overlaps:
                consumed_spans.append((start_idx, end_idx))
                matched.append((name, bounds))

    return matched


def resolve_gazetteer_bounds(text: str) -> Optional[SpatialBounds]:
    """
    Resolves a query string to a single SpatialBounds if exactly one recognized
    region is present. If multiple regions or zero regions match, returns None.

    Args:
        text: Natural language user query string.

    Returns:
        SpatialBounds copy if exactly one region matches, else None.
    """
    matches = find_matching_regions(text)
    if len(matches) == 1:
        _, bounds = matches[0]
        return SpatialBounds(
            latitude_min=bounds.latitude_min,
            latitude_max=bounds.latitude_max,
            longitude_min=bounds.longitude_min,
            longitude_max=bounds.longitude_max,
        )
    return None

