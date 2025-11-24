# bytes per gibibyte
BYTES_PER_GB = 1024 ** 3

# storage price per GB per month (Germany West Central, RA GRS, HNS)
# values in £ per GB·month
PRICE_PER_GB_MONTH = {
    "Hot": 0.0371,
    "Cool": 0.01889,
    "Cold": 0.00763,
    "Archive": 0.00211,
}

# read operation price per 10,000 operations
# values in £ per 10,000 reads
READ_PRICE_PER_10K = {
    "Hot": 0.0044,
    "Cool": 0.0100,
    "Cold": 0.1000,
    "Archive": 5.5000,
}

# list of tiers we consider
TIERS = ["Hot", "Cool", "Cold", "Archive"]


# normalise tier names to our keys
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


# estimate read operation cost based on a total read count
def estimate_read_cost_month(reads_count: int, tier: str) -> float:
    # normalised tier
    t = _tier(tier)
    # price per 10,000 reads
    price_per_10k = READ_PRICE_PER_10K[t]
    # cost = (reads / 10,000) * price_per_10k
    return (reads_count / 10000.0) * price_per_10k


# estimate total cost (capacity + reads) for a given tier
def estimate_total_month(size_bytes: int, reads_count: int, tier: str) -> float:
    # capacity cost
    cap = estimate_capacity_month(size_bytes=size_bytes, tier=tier)
    # read cost
    reads = estimate_read_cost_month(reads_count=reads_count, tier=tier)
    # total
    return cap + reads


# find cheapest / best tier based on size, total reads, and extra metadata
def find_optimal_tier(
    size_bytes: int,
    reads_count: int,
    criticality_index: int = 0,
    has_historical_links: bool = False,
    days_since_last_access: int | None = None,
    days_since_creation: int | None = None,
    human_trigger_index: int = 0,
    planned_activities_6m: bool = False,
    media_relevance: int = 0,
):
    """
    Decide an optimal tier for a blob.

    - criticality_index: 0..5 (5 = highest importance)
    - has_historical_links: bool
    - days_since_last_access: int days or None
    - days_since_creation: int days or None
    - human_trigger_index: 0..5 (5 = very likely manual access)
    - planned_activities_6m: bool (if blob is likely to be accessed)
    - media_relevance: 0..5 (5 = will matter a lot in future)
    """
    # store per-tier raw costs based on size and reads
    costs: dict[str, float] = {}

    for t in TIERS:
        costs[t] = estimate_total_month(
            size_bytes=size_bytes,
            reads_count=reads_count,
            tier=t,
        )

    # Normalise metadata into 0..1 weights where possible

    criticality = max(0, min(criticality_index, 5)) / 5.0
    relevance = max(0, min(media_relevance, 5)) / 5.0
    human = max(0, min(human_trigger_index, 5)) / 5.0
    planned = 1.0 if planned_activities_6m else 0.0

    # clamp age to minimum 0 days and max 2 years
    if days_since_last_access is not None:
        age_days = max(0, min(days_since_last_access, 730))
    elif days_since_creation is not None:
        age_days = max(0, min(days_since_creation, 730))
    else:
        # no access info and no creation date
        age_days = 730

    age = age_days / 730.0  # 0 = fresh, 1 = very old

    # higher heat means we want a hotter tier
    heat = (
        (0.30 * criticality) +
        (0.25 * relevance) +
        (0.20 * human) +
        (0.15 * planned) +
        (0.10 * (1.0 - age))
    )

    # map heat to a "target" tier index

    tier_index = {name: idx for idx, name in enumerate(TIERS)}

    if heat >= 0.75:
        target_idx = tier_index["Hot"]
    elif heat >= 0.50:
        target_idx = tier_index["Cool"]
    elif heat >= 0.25:
        target_idx = tier_index["Cold"]
    else:
        target_idx = tier_index["Archive"]

    # combine cost + penalties into a final score per tier

    tier_scores: dict[str, float] = {}

    for t in TIERS:
        base_cost = costs[t]
        idx = tier_index[t]

        # basic distance penalty: further from target tier -> worse
        distance = abs(idx - target_idx)
        penalty = 1.0 + 0.5 * distance  # 0 steps = 1.0, 1 step = 1.5, etc.

        # high criticality / relevance: strongly discourage Archive
        if t == "Archive":
            if criticality >= 0.8 or relevance >= 0.8:
                penalty *= 5.0

        # expected future usage or human activity: avoid Cold / Archive
        if t in ("Cold", "Archive"):
            if planned or human >= 0.6:
                penalty *= 2.0

        # historical blobs that are not very "hot" are allowed to drift colder
        if has_historical_links and heat < 0.5 and t in ("Cold", "Archive"):
            penalty *= 0.7  # slightly favour colder tiers

        # very large blobs: gently steer away from expensive hot tiers
        size_gb = size_bytes / BYTES_PER_GB if size_bytes is not None else 0
        if size_gb > 100 and t in ("Hot", "Cool"):
            penalty *= 1.2

        tier_scores[t] = base_cost * penalty

    # pick tier with the lowest (cost * penalty)
    best_tier = min(tier_scores, key=tier_scores.get)

    best_cost = costs[best_tier]
    return best_tier, best_cost, costs
