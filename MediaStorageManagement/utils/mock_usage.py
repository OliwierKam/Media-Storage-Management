from datetime import datetime, timedelta, timezone
import hashlib
import random

# how many days of fake history to build
MAX_HISTORY_DAYS = 365


def _rng_for_blob(container_name, blob_name):
    # Deterministic stable random generator for this blob
    key = f"{container_name}/{blob_name}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    seed = int(digest[:8], 16)
    return random.Random(seed)


def _profile_for_blob(container_name, blob_name):
    """
    decide how "hot" this blob is overall

    hot = often read (many days with reads)
    cool = sometimes read
    cold = rarely read
    archive = almost never read
    """
    rng = _rng_for_blob(container_name, blob_name)
    roll = rng.randint(0, 99)

    # 20%
    if roll < 20:
        return "hot"
    # 30%
    if roll < 50:
        return "cool"
    # 30%
    if roll < 80:
        return "cold"
    # Remaining 20%
    return "archive"


# simple settings for each profile:
# - prob_per_day: chance that the blob is read on a given day
# - max_reads:    max reads on a "read" day
PROFILE_SETTINGS = {
    "hot": {
        "prob_per_day": 0.7,  # ~70% of days
        "max_reads": 6,       # 1-6 reads on those days
    },
    "cool": {
        "prob_per_day": 0.3,  # ~30% of days
        "max_reads": 4,       # 1-4 reads
    },
    "cold": {
        "prob_per_day": 0.08, # ~8% of days
        "max_reads": 3,       # 1-3 reads
    },
    "archive": {
        "prob_per_day": 0.01, # ~1% of days
        "max_reads": 2,       # 1-2 reads
    },
}


# Builds fake list
def generate_mock_history(container_name, blob_name, days=MAX_HISTORY_DAYS):
    # clamp to allowed range
    days = max(1, min(days, MAX_HISTORY_DAYS))

    # stable rng and profile
    rng = _rng_for_blob(container_name, blob_name)
    profile = _profile_for_blob(container_name, blob_name)
    settings = PROFILE_SETTINGS[profile]
    now = datetime.now(timezone.utc)

    history = []

    for i in range(days):
        # this day (today - i)
        day = now - timedelta(days=i)

        # decide if blob was read at all on this day
        if rng.random() < settings["prob_per_day"]:
            # it was read: pick 1..max_reads
            reads_today = rng.randint(1, settings["max_reads"])
        else:
            # no reads
            reads_today = 0

        history.append(
            {
                "date": day,
                "reads": reads_today,
            }
        )

    # returns list of dicts
    return history


# look at total reads in the last window_days days and find the most recent day with reads
def get_mock_access_window(container_name, blob_name, window_days):
    # generate full history
    full_history = generate_mock_history(
        container_name=container_name,
        blob_name=blob_name,
        days=MAX_HISTORY_DAYS,
    )

    # clamp the window to valid bounds
    window_days = max(1, min(window_days, len(full_history)))
    # take only the most recent window_days entries
    history_window = full_history[:window_days]

    total_reads = 0
    last_accessed_on = None

    # loop through each day in the window
    for entry in history_window:
        # number of reads for this day
        reads = entry["reads"]

        # add to total
        total_reads += reads

        # if this day has reads and we haven't recorded a last access yet
        if reads > 0 and last_accessed_on is None:
            # store this date as most recent access
            last_accessed_on = entry["date"]

    # return last access date, total reads, and window list
    return last_accessed_on, total_reads, history_window


# Extra mocked metadata for multi-factor tiering
def get_mock_blob_metadata(container_name, blob_name):
    """
    Return a dict of mocked attributes for this blob:

    - criticality_index: Scalar 0-5 (5 = highest importance)
    - has_historical_links: bool
    - days_since_last_access: int days (could be None)
    - human_trigger_index: Scalar 0-5 (5 = very likely manual access)
    - planned_activities_6m: bool (if blob is likely to be accessed)
    - media_relevance: 0-5 (5 = will matter a lot in future)

    All values are deterministic per (container_name, blob_name).
    """
    rng = _rng_for_blob(container_name, blob_name)
    profile = _profile_for_blob(container_name, blob_name)

    criticality_index = rng.randint(0, 5)

    # Assume around a quarter of blobs have historical links
    has_historical_links = rng.random() < 0.25

    # tie "last access" to the mocked access history
    now = datetime.now(timezone.utc)
    last_accessed_on, total_reads, _history = get_mock_access_window(
        container_name=container_name,
        blob_name=blob_name,
        window_days=MAX_HISTORY_DAYS,
    )

    if last_accessed_on is not None:
        # how long since we last accessed the blob
        days_since_last_access = (now - last_accessed_on).days

        # defensively clamp negatives
        if days_since_last_access < 0:
            days_since_last_access = 0
    else:
        # never accessed in our history
        days_since_last_access = None

    human_trigger_index = rng.randint(0, 5)

    # planned activities is a boolean but weighted by profile to simulate realism
    if profile == "hot":
        planned_prob = 0.7
    elif profile == "cool":
        planned_prob = 0.4
    elif profile == "cold":
        planned_prob = 0.15
    else:  # archive
        planned_prob = 0.05

    planned_activities_6m = rng.random() < planned_prob

    media_relevance = rng.randint(0, 5)

    return {
        "criticality_index": criticality_index,
        "has_historical_links": has_historical_links,
        "days_since_last_access": days_since_last_access,
        "human_trigger_index": human_trigger_index,
        "planned_activities_6m": planned_activities_6m,
        "media_relevance": media_relevance,
    }
