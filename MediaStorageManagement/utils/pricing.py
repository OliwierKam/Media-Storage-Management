from dataclasses import dataclass

BYTES_PER_GB = 1024 ** 3

# Germany West Central • RA-GRS • HNS — £ per GB-month
PRICE_PER_GB_MONTH = {
    "Hot":     0.0371,
    "Cool":    0.01889,
    "Cold":    0.00763,
    "Archive": 0.00211,
}

# OPTIONAL usage rates — rough placeholders.
BANDWIDTH_PRICE_PER_GB = 0.05   # outbound to internet (example)
INGRESS_PRICE_PER_GB   = 0.00   # inbound is typically £0 for Azure

# If I can later include per-10k operation costs, keep this.
PRICE_PER_10K_OPS = {
    "Hot":     {"read": 0.0043, "write": 0.1058, "other": 0.0043},
    "Cool":    {"read": 0.0099, "write": 0.1964, "other": 0.0043},
    "Cold":    {"read": 0.0982, "write": 0.3535, "other": 0.0043},
    "Archive": {"read": 5.2770, "write": 0.2259, "other": 0.0043},
}

def _tier(t):
    s = str(t or "").lower()
    if "hot" in s: return "Hot"
    if "cool" in s: return "Cool"
    if "cold" in s: return "Cold"
    if "archive" in s: return "Archive"
    return "Hot"

def estimate_capacity_month(size_bytes: int, tier: str) -> float:
    # Capacity-only monthly estimate for the blob's CURRENT tier.
    t = _tier(tier)
    price = PRICE_PER_GB_MONTH[t]
    return (size_bytes / BYTES_PER_GB) * price

@dataclass
class Usage:
    # All optional — pass zeros until you I have real numbers
    egress_gb: float = 0.0 # GB downloaded out of Azure/internet
    ingress_gb: float = 0.0 # GB uploaded into Azure
    reads: int = 0 # if you choose to count app reads
    writes: int = 0 # if you choose to count app writes
    other_ops: int = 0 # metadata/tag/list/etc.

def estimate_usage_month(tier: str, u: Usage) -> float:
    # usage cost = bandwidth + optional ops.

    # bandwidth
    bw_cost = u.egress_gb * BANDWIDTH_PRICE_PER_GB + u.ingress_gb * INGRESS_PRICE_PER_GB

    # optional ops
    t = _tier(tier)
    rates = PRICE_PER_10K_OPS[t]
    ops_cost = (u.reads/10000.0) * rates["read"] + (u.writes/10000.0) * rates["write"] + (u.other_ops/10000.0) * rates["other"]

    return bw_cost + ops_cost

def estimate_total_month(size_bytes: int, tier: str, usage: Usage) -> dict:
    cap = estimate_capacity_month(size_bytes, tier)
    use = estimate_usage_month(tier, usage)
    return {"capacity": cap, "usage": use, "total": cap + use}
