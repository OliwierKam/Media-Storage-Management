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

    # global config
    MAX_AGE_DAYS = 730  # clamp age at 2 years

    # how different metadata contributes to "heat" (0..1)
    HEAT_WEIGHT_CRITICALITY = 0.28
    HEAT_WEIGHT_RELEVANCE = 0.22
    HEAT_WEIGHT_HUMAN = 0.20
    HEAT_WEIGHT_PLANNED = 0.15
    HEAT_WEIGHT_FRESHNESS = 0.15

    # heat suggested tier mapping
    HEAT_THRESHOLD_HOT = 0.75
    HEAT_THRESHOLD_COOL = 0.50
    HEAT_THRESHOLD_COLD = 0.25

    # generic penalties applied on top of raw cost
    DISTANCE_PENALTY_PER_STEP = 0.5
    ARCHIVE_HIGH_IMPORTANCE_PENALTY = 5.0
    COLD_ARCHIVE_FUTURE_USAGE_PENALTY = 3.0
    HISTORICAL_COLD_DISCOUNT = 0.5
    LARGE_HOT_COOL_PENALTY = 1.2

    # size-related thresholds (GB) for extra nudges away from Hot/Cool
    LARGE_BLOB_THRESHOLD_GB = 100.0
    VERY_LARGE_BLOB_THRESHOLD_GB = 1024.0
    VERY_LARGE_HOT_PENALTY = 3.0

    # hard rules and age-based tweaks
    CRITICALITY_NO_ARCHIVE_THRESHOLD = 0.6
    RECENT_ACCESS_NO_ARCHIVE_DAYS = 30
    RECENT_ACCESS_NO_COLD_DAYS = 30

    OLD_AGE_DAYS = 365
    VERY_OLD_AGE_DAYS = 540
    OLD_HEAT_THRESHOLD = 0.4
    VERY_OLD_HEAT_THRESHOLD = 0.3
    OLD_HOT_COOL_PENALTY = 1.5
    VERY_OLD_HOT_PENALTY = 3.0

    # historical data preferences
    LOW_CRITICALITY_HISTORICAL_THRESHOLD = 0.4

    # archive-specific rules (rehydration makes it unsuitable for near-term use)
    PLANNED_NO_ARCHIVE = True
    HUMAN_NO_ARCHIVE_THRESHOLD = 0.6

    # store per-tier raw costs (no penalties yet)
    costs: dict[str, float] = {}
    for t in TIERS:
        costs[t] = estimate_total_month(
            size_bytes=size_bytes,
            reads_count=reads_count,
            tier=t,
        )

    # normalise metadata into 0..1
    criticality = max(0, min(criticality_index, 5)) / 5.0
    relevance = max(0, min(media_relevance, 5)) / 5.0
    human = max(0, min(human_trigger_index, 5)) / 5.0
    planned = 1.0 if planned_activities_6m else 0.0

    # derive age in days (prefer last access, then creation, else "very old")
    if days_since_last_access is not None:
        age_days = max(0, min(days_since_last_access, MAX_AGE_DAYS))
    elif days_since_creation is not None:
        age_days = max(0, min(days_since_creation, MAX_AGE_DAYS))
    else:
        age_days = MAX_AGE_DAYS

    age = age_days / float(MAX_AGE_DAYS)  # 0 = fresh, 1 = old

    # compute "heat" score (higher = we prefer hotter tiers)
    heat = (
        (HEAT_WEIGHT_CRITICALITY * criticality) +
        (HEAT_WEIGHT_RELEVANCE * relevance) +
        (HEAT_WEIGHT_HUMAN * human) +
        (HEAT_WEIGHT_PLANNED * planned) +
        (HEAT_WEIGHT_FRESHNESS * (1.0 - age))
    )

    # map heat → suggested target tier
    tier_index = {name: idx for idx, name in enumerate(TIERS)}

    if heat >= HEAT_THRESHOLD_HOT:
        target_idx = tier_index["Hot"]
    elif heat >= HEAT_THRESHOLD_COOL:
        target_idx = tier_index["Cool"]
    elif heat >= HEAT_THRESHOLD_COLD:
        target_idx = tier_index["Cold"]
    else:
        target_idx = tier_index["Archive"]

    # hard disallowed tiers (policy / semantics)
    disallowed_tiers: set[str] = set()

    # critical blobs should not be in Archive
    if criticality >= CRITICALITY_NO_ARCHIVE_THRESHOLD:
        disallowed_tiers.add("Archive")

    # recent access: keep in warmer tiers
    if days_since_last_access is not None:
        if days_since_last_access < RECENT_ACCESS_NO_ARCHIVE_DAYS:
            disallowed_tiers.add("Archive")
        if days_since_last_access < RECENT_ACCESS_NO_COLD_DAYS:
            disallowed_tiers.add("Cold")

    # newly created blobs should not go straight to Archive
    if days_since_creation is not None:
        if days_since_creation < RECENT_ACCESS_NO_ARCHIVE_DAYS:
            disallowed_tiers.add("Archive")

    # known near-future use: do not Archive
    if PLANNED_NO_ARCHIVE and planned_activities_6m:
        disallowed_tiers.add("Archive")

    # strong human usage signal: avoid Archive
    if human >= HUMAN_NO_ARCHIVE_THRESHOLD:
        disallowed_tiers.add("Archive")

    # combine raw cost + penalties for each allowed tier
    tier_scores: dict[str, float] = {}

    for t in TIERS:
        if t in disallowed_tiers:
            continue

        base_cost = costs[t]
        idx = tier_index[t]

        # gently punish tiers far from the heat-based target
        distance = abs(idx - target_idx)
        penalty = 1.0 + DISTANCE_PENALTY_PER_STEP * distance

        # discourage putting relevant blobs into Archive (critically already addressed earlier)
        if t == "Archive":
            if relevance >= 0.6:
                penalty *= ARCHIVE_HIGH_IMPORTANCE_PENALTY

        # avoid Cold/Archive for near-term or human-driven workloads
        if t in ("Cold", "Archive"):
            if planned or human >= 0.6:
                penalty *= COLD_ARCHIVE_FUTURE_USAGE_PENALTY

        # low-criticality historical content is cheaper to keep cold
        if has_historical_links:
            if criticality < LOW_CRITICALITY_HISTORICAL_THRESHOLD:
                if heat < 0.5 and t in ("Cold", "Archive"):
                    penalty *= HISTORICAL_COLD_DISCOUNT

        # older, low-heat data should drift away from hot tiers
        if age_days > OLD_AGE_DAYS:
            if heat < OLD_HEAT_THRESHOLD and t in ("Hot", "Cool"):
                penalty *= OLD_HOT_COOL_PENALTY

        if age_days > VERY_OLD_AGE_DAYS:
            if heat < VERY_OLD_HEAT_THRESHOLD and t == "Hot":
                penalty *= VERY_OLD_HOT_PENALTY

        # size-based nudges away from Hot/Cool for large blobs
        size_gb = size_bytes / BYTES_PER_GB if size_bytes is not None else 0

        if size_gb > LARGE_BLOB_THRESHOLD_GB and t in ("Hot", "Cool"):
            penalty *= LARGE_HOT_COOL_PENALTY

        if size_gb > VERY_LARGE_BLOB_THRESHOLD_GB and t == "Hot":
            penalty *= VERY_LARGE_HOT_PENALTY

        tier_scores[t] = base_cost * penalty

    # pick tier with the lowest (cost * penalty)
    best_tier = min(tier_scores, key=tier_scores.get)
    best_cost = costs[best_tier]

    return best_tier, best_cost, costs
