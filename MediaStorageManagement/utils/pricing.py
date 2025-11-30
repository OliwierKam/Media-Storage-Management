# Conversion constant since azure uses GB
BYTES_PER_GB = 1024 ** 3

# Storage price per GB per month (Germany West Central, RA GRS, HNS).
# All values are in £ per GB month.
PRICE_PER_GB_MONTH = {
    "Hot": 0.0371,
    "Cool": 0.01889,
    "Cold": 0.00763,
    "Archive": 0.00211,
}

# Read operation price per 10,000 operations.
# All values are in £ per 10,000 reads.
READ_PRICE_PER_10K = {
    "Hot": 0.0044,
    "Cool": 0.0100,
    "Cold": 0.1000,
    "Archive": 5.5000,
}

# Tiers
TIERS = ["Hot", "Cool", "Cold", "Archive"]

# Normalise any tier input
def _tier(t):

    # Turn it into a string and lower-case
    s = str(t or "").lower()

    # Very simple substring checks. This deliberately allows values like "hot lrs" or "cool_zrs" to still map correctly.
    if "hot" in s:
        return "Hot"
    if "cool" in s:
        return "Cool"
    if "cold" in s:
        return "Cold"
    if "archive" in s:
        return "Archive"

    # Fallback
    return "Hot"

# Estimate the monthly capacity cost for a blob in a given tier.
def estimate_capacity_month(size_bytes: int, tier: str) -> float:

    # Normalise
    t = _tier(tier)

    # Look up the price per GB per month for that tier.
    price_per_gb_month = PRICE_PER_GB_MONTH[t]

    # Convert bytes → GB and multiply by the unit price.
    size_gb = size_bytes / BYTES_PER_GB
    capacity_cost = size_gb * price_per_gb_month

    return capacity_cost

# Estimate monthly read operation cost for a given tier.
def estimate_read_cost_month(reads_count: int, tier: str) -> float:

    # Again normalise the tier first.
    t = _tier(tier)

    # Azure pricing is typically given per 10,000 read operations.
    price_per_10k = READ_PRICE_PER_10K[t]

    read_cost = (reads_count / 10000.0) * price_per_10k

    return read_cost

# Combined monthly cost estimate (capacity + reads) for a blob.
def estimate_total_month(size_bytes: int, reads_count: int, tier: str) -> float:

    # Capacity component.
    capacity_cost = estimate_capacity_month(size_bytes=size_bytes, tier=tier)

    # Read operation component.
    read_cost = estimate_read_cost_month(reads_count=reads_count, tier=tier)

    # Simple sum
    total = capacity_cost + read_cost

    return total


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
    Decide which tier is "best" for a blob, based on both cost and metadata.

    The core idea:
    For each tier, first compute a raw monthly cost.
    Then apply a penalty or discount factor depending on:
    - how "hot" the blob looks (importance, recency, human usage, etc.)
    - how far a candidate tier is from the "ideal" heat level
    - some simple policies (e.g. critical blobs should not be archived)
    - size/age tweaks (very large or very old data tends to go colder)
    """

    # Global configuration

    # We clamp ages to at most 2 years
    MAX_AGE_DAYS = 730  # 2 years

    # How much different factors contribute to the "heat" score.
    HEAT_WEIGHT_CRITICALITY = 0.28
    HEAT_WEIGHT_RELEVANCE = 0.22
    HEAT_WEIGHT_HUMAN = 0.20
    HEAT_WEIGHT_PLANNED = 0.15
    HEAT_WEIGHT_FRESHNESS = 0.15

    # Heat thresholds for picking an "ideal" tier before costs.
    HEAT_THRESHOLD_HOT = 0.75
    HEAT_THRESHOLD_COOL = 0.50
    HEAT_THRESHOLD_COLD = 0.25

    # Generic penalty parameters that sit on top of the raw cost.
    DISTANCE_PENALTY_PER_STEP = 0.5
    ARCHIVE_HIGH_IMPORTANCE_PENALTY = 5.0
    COLD_ARCHIVE_FUTURE_USAGE_PENALTY = 3.0
    HISTORICAL_COLD_DISCOUNT = 0.5
    LARGE_HOT_COOL_PENALTY = 1.2

    # Size thresholds (in GB) for nudging large blobs away from hot tiers.
    LARGE_BLOB_THRESHOLD_GB = 100.0
    VERY_LARGE_BLOB_THRESHOLD_GB = 1024.0
    VERY_LARGE_HOT_PENALTY = 3.0

    # Hard-ish rules and age-based tweaks.
    CRITICALITY_NO_ARCHIVE_THRESHOLD = 0.6
    RECENT_ACCESS_NO_ARCHIVE_DAYS = 30
    RECENT_ACCESS_NO_COLD_DAYS = 30

    OLD_AGE_DAYS = 365
    VERY_OLD_AGE_DAYS = 540
    OLD_HEAT_THRESHOLD = 0.4
    VERY_OLD_HEAT_THRESHOLD = 0.3
    OLD_HOT_COOL_PENALTY = 1.5
    VERY_OLD_HOT_PENALTY = 3.0

    # Historical data
    LOW_CRITICALITY_HISTORICAL_THRESHOLD = 0.4

    # Archive-specific rules
    PLANNED_NO_ARCHIVE = True
    HUMAN_NO_ARCHIVE_THRESHOLD = 0.6

    # Base cost per tier (without any penalties or metadata)

    # This dict holds the raw cost for each tier, assuming the same size and read count.
    costs: dict[str, float] = {}

    for t in TIERS:
        raw_cost = estimate_total_month(
            size_bytes=size_bytes,
            reads_count=reads_count,
            tier=t,
        )
        costs[t] = raw_cost

    # Normalise metadata into 0..1 ranges

    criticality_index_clamped = max(0, min(criticality_index, 5))
    relevance_index_clamped = max(0, min(media_relevance, 5))
    human_index_clamped = max(0, min(human_trigger_index, 5))

    criticality = criticality_index_clamped / 5.0
    relevance = relevance_index_clamped / 5.0
    human = human_index_clamped / 5.0
    planned = 1.0 if planned_activities_6m else 0.0

    # Derive an age (0 = fresh, 1 = old)

    if days_since_last_access is not None:
        clamped = max(0, min(days_since_last_access, MAX_AGE_DAYS))
        age_days = clamped
    elif days_since_creation is not None:
        clamped = max(0, min(days_since_creation, MAX_AGE_DAYS))
        age_days = clamped
    else:
        age_days = MAX_AGE_DAYS

    # Normalise to 0..1
    age = age_days / float(MAX_AGE_DAYS)  # 0 means very fresh, 1 means very old

    # Compute a "heat" score

    heat = (
        (HEAT_WEIGHT_CRITICALITY * criticality)
        + (HEAT_WEIGHT_RELEVANCE * relevance)
        + (HEAT_WEIGHT_HUMAN * human)
        + (HEAT_WEIGHT_PLANNED * planned)
        + (HEAT_WEIGHT_FRESHNESS * (1.0 - age))
    )

    # Map heat to a "target" tier index

    # Build a simple mapping from tier name to integer index.
    tier_index: dict[str, int] = {}
    i = 0
    while i < len(TIERS):
        name = TIERS[i]
        tier_index[name] = i
        i = i + 1

    # Now decide which index is ideal based on hear
    if heat >= HEAT_THRESHOLD_HOT:
        target_idx = tier_index["Hot"]
    elif heat >= HEAT_THRESHOLD_COOL:
        target_idx = tier_index["Cool"]
    elif heat >= HEAT_THRESHOLD_COLD:
        target_idx = tier_index["Cold"]
    else:
        target_idx = tier_index["Archive"]

    # Build a set of tiers that are completely disallowed

    disallowed_tiers: set[str] = set()

    # Highly critical data should never be in Archive.
    if criticality >= CRITICALITY_NO_ARCHIVE_THRESHOLD:
        disallowed_tiers.add("Archive")

    # If we've accessed this blob very recently, avoid chilling it too much.
    if days_since_last_access is not None:
        if days_since_last_access < RECENT_ACCESS_NO_ARCHIVE_DAYS:
            disallowed_tiers.add("Archive")
        if days_since_last_access < RECENT_ACCESS_NO_COLD_DAYS:
            disallowed_tiers.add("Cold")

    # New blobs should not go straight to Archive either.
    if days_since_creation is not None:
        if days_since_creation < RECENT_ACCESS_NO_ARCHIVE_DAYS:
            disallowed_tiers.add("Archive")

    # If we know there is planned activity soon, do not Archive it.
    if PLANNED_NO_ARCHIVE and planned_activities_6m:
        disallowed_tiers.add("Archive")

    # Strong human usage signal: also avoid Archive.
    if human >= HUMAN_NO_ARCHIVE_THRESHOLD:
        disallowed_tiers.add("Archive")

    # 7) Combine raw cost + penalties into a "score" per tier

    tier_scores: dict[str, float] = {}

    for t in TIERS:
        # Skip any tier that is completely disallowed.
        if t in disallowed_tiers:
            continue

        base_cost = costs[t]
        idx = tier_index[t]

        # Start with a neutral penalty (1.0 = no change).
        penalty = 1.0

        # Slightly punish tiers that are far from the heat-based target.
        distance = abs(idx - target_idx)
        penalty = penalty + DISTANCE_PENALTY_PER_STEP * distance

        # Strong reason not to use Archive for high-importance content.
        if t == "Archive":
            if relevance >= 0.6:
                penalty = penalty * ARCHIVE_HIGH_IMPORTANCE_PENALTY

        # Avoid Cold/Archive if the blob will be accessed in the near future or is heavily human-driven.
        if t == "Cold" or t == "Archive":
            if planned_activities_6m or human >= 0.6:
                penalty = penalty * COLD_ARCHIVE_FUTURE_USAGE_PENALTY

        # For historical blobs that are not very critical, colder storage is often a good deal
        if has_historical_links:
            if criticality < LOW_CRITICALITY_HISTORICAL_THRESHOLD:
                if heat < 0.5 and (t == "Cold" or t == "Archive"):
                    penalty = penalty * HISTORICAL_COLD_DISCOUNT

        # Older, low-heat data should not sit in expensive hot tiers forever.
        if age_days > OLD_AGE_DAYS:
            if heat < OLD_HEAT_THRESHOLD and (t == "Hot" or t == "Cool"):
                penalty = penalty * OLD_HOT_COOL_PENALTY

        if age_days > VERY_OLD_AGE_DAYS:
            if heat < VERY_OLD_HEAT_THRESHOLD and t == "Hot":
                penalty = penalty * VERY_OLD_HOT_PENALTY

        # Size-based adjustments

        size_gb = 0.0
        if size_bytes is not None:
            size_gb = size_bytes / BYTES_PER_GB

        # Large blobs in Hot or Cool can get expensive quickly.
        if size_gb > LARGE_BLOB_THRESHOLD_GB and (t == "Hot" or t == "Cool"):
            penalty = penalty * LARGE_HOT_COOL_PENALTY

        # Very large blobs really should not be in Hot unless there is a very strong reason
        if size_gb > VERY_LARGE_BLOB_THRESHOLD_GB and t == "Hot":
            penalty = penalty * VERY_LARGE_HOT_PENALTY

        # Final score is raw_cost * penalty. Lower is better.
        score = base_cost * penalty
        tier_scores[t] = score

    # Pick the tier with the lowest score

    best_tier = min(tier_scores, key=lambda name: tier_scores[name])

    # Return the raw cost for that tier (not the penalised score),
    best_cost = costs[best_tier]
    return best_tier, best_cost, costs
