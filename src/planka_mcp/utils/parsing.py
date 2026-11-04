def parse_collection(data, field: str = "items"):
    # Planka wraps collections in {"items": [...], "pagination": {...}};
    # fall back to a bare list defensively.
    return data.get(field, []) if isinstance(data, dict) else (data or [])


def normalize(query: str) -> str:
    """Normalize strings"""
    return query.strip().casefold()
