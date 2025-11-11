BYTES_PER_GB = 1024 ** 3

# For Germany West Central, RA GRS Redundancy, Hierarchical Namespace
PRICE_PER_GB_MONTH = {
    "Hot":     0.0371,
    "Cool":    0.01889,
    "Cold":    0.00763,
    "Archive": 0.00211,
}

def _tier(t):
    s = str(t or "").lower()
    if "hot" in s: return "Hot"
    if "cool" in s: return "Cool"
    if "cold" in s: return "Cold"
    if "archive" in s: return "Archive"
    return "Hot"

def estimate_capacity_month(size_bytes: int, tier: str) -> float:
    t = _tier(tier)
    price = PRICE_PER_GB_MONTH[t]
    return (size_bytes / BYTES_PER_GB) * price
