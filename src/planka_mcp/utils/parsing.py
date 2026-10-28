def parse_collection(data):
    # Planka wraps collections in {"items": [...], "pagination": {...}};
    # fall back to a bare list defensively.
    return data.get("items", []) if isinstance(data, dict) else (data or [])
