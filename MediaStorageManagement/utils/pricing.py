# bytes per gibibyte
BYTES_PER_GB = 1024 ** 3

# storage price per GB per month (Germany West Central, RA GRS, HNS)

# values in £ per GB·month
PRICE_PER_GB_MONTH = {
    "Hot":     0.0371,
    "Cool":    0.01889,
    "Cold":    0.00763,
    "Archive": 0.00211,
}

# read operation price per 10,000 operations
READ_PRICE_PER_10K = {
    "Hot":     0.0044,
    "Cool":    0.0100,
    "Cold":    0.1000,
    "Archive": 5.5000,
}

# normalise tier names
def _tier(t):
    # cast to string and lower for safety
    s = str(t or "").lower()
    # map by substring
    if "hot" in s:
        return "Hot"
    if "cool" in s:
        return "Cool"
    if "cold" in s:
        return "Cold"
    if "archive" in s:
        return "Archive"
    # default to Hot if unknown
    return "Hot"

# estimate capacity cost per month for a blob
def estimate_capacity_month(size_bytes: int, tier: str) -> float:
    # normalised tier
    t = _tier(tier)
    # unit price per GB per month
    price = PRICE_PER_GB_MONTH[t]
    # convert bytes to GB and multiply by price
    return (size_bytes / BYTES_PER_GB) * price

# estimate read operation cost per month
def estimate_read_cost_month(reads_30_days: int, tier: str) -> float:
    # normalised tier
    t = _tier(tier)
    # price per 10,000 reads
    price_per_10k = READ_PRICE_PER_10K[t]
    # cost = (reads / 10,000) * price_per_10k
    return (reads_30_days / 10000.0) * price_per_10k
