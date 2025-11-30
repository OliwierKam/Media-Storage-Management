from datetime import datetime, timedelta, timezone
import hashlib
import random

# How many days of fake access history to simulate for each blob.
# The rest of the code assumes the history never gets longer than this.
MAX_HISTORY_DAYS = 365

# INTERNAL HELPERS

# Builds a deterministic random number generator for a given blob.
def _rng_for_blob(container_name, blob_name):

    # Combine container name and blob name into one string.
    key = f"{container_name}/{blob_name}"

    # Turn that string into a SHA-256 hash, then into hex.
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()

    # Take the first 8 hex characters and convert them to an integer.
    # This is enough for a reasonably spread-out seed.
    seed = int(digest[:8], 16)

    # Use Python's Random class with that seed so every call is reproducible.
    return random.Random(seed)

# Decide how "hot" this blob is overall, based on a random roll.
def _profile_for_blob(container_name, blob_name):

    rng = _rng_for_blob(container_name, blob_name)
    roll = rng.randint(0, 99)  # random integer 0..99

    # 0-19  (20%)
    if roll < 20:
        return "hot"

    # 20-49 (30%)
    if roll < 50:
        return "cool"

    # 50-79 (30%)
    if roll < 80:
        return "cold"

    # 80-99 (20%)
    return "archive"


# Settings for each profile:
# - prob_per_day: how likely it is that the blob receives at least one read on a given day.
# - max_reads: the maximum number of reads on a day when it is accessed.
PROFILE_SETTINGS = {
    "hot": {
        "prob_per_day": 0.7, # blob is accessed on about 70% of days
        "max_reads": 6, # between 1 and 6 reads on those days
    },
    "cool": {
        "prob_per_day": 0.3,
        "max_reads": 4,
    },
    "cold": {
        "prob_per_day": 0.08,
        "max_reads": 3,
    },
    "archive": {
        "prob_per_day": 0.01,
        "max_reads": 2,
    },
}

# HISTORY GENERATION

# Build a fake per-day access history for this blob.
def generate_mock_history(container_name, blob_name, days=MAX_HISTORY_DAYS):

    # Make sure the number of days is within a sensible range
    if days < 1:
        days = 1
    if days > MAX_HISTORY_DAYS:
        days = MAX_HISTORY_DAYS

    # Create a stable RNG and a usage profile for this blob.
    rng = _rng_for_blob(container_name, blob_name)
    profile = _profile_for_blob(container_name, blob_name)
    settings = PROFILE_SETTINGS[profile]

    # Use "now" as the reference point and walk backwards in time.
    now = datetime.now(timezone.utc)

    history = []

    # For each day back from today (0 = today, 1 = yesterday, etc.)
    i = 0
    while i < days:
        # Compute the date for this entry.
        day = now - timedelta(days=i)

        # Decide if the blob was accessed at all on this day.
        if rng.random() < settings["prob_per_day"]:
            # If yes, choose a random number of reads between 1 and max_reads.
            reads_today = rng.randint(1, settings["max_reads"])
        else:
            # If not, reads are 0.
            reads_today = 0

        # Store one entry per day.
        history.append(
            {
                "date": day,
                "reads": reads_today,
            }
        )

        i = i + 1

    # The calling code expects the list of dictionaries.
    return history

# Look at the most recent window_days worth of history
def get_mock_access_window(container_name, blob_name, window_days):

    # First generate the full fake history for this blob.
    full_history = generate_mock_history(
        container_name=container_name,
        blob_name=blob_name,
        days=MAX_HISTORY_DAYS,
    )

    # Make sure the requested window is between 1 day and the length of the history
    if window_days < 1:
        window_days = 1
    if window_days > len(full_history):
        window_days = len(full_history)

    # Take only the most recent N days (history is already newest-first).
    history_window = full_history[:window_days]

    total_reads = 0
    last_accessed_on = None

    # Go through each day in the window and accumulate reads.
    for entry in history_window:
        # How many reads happened on this day.
        reads = entry["reads"]

        # Add to the running total.
        total_reads = total_reads + reads

        # If haven't recorded a last access yet and this day has reads, treat this as the most recent access.
        if reads > 0 and last_accessed_on is None:
            last_accessed_on = entry["date"]

    # Return the last access date, total reads, and the window used.
    return last_accessed_on, total_reads, history_window

# EXTRA MOCKED METADATA

# Build a small dictionary of fake "business" metadata for a blob.
def get_mock_blob_metadata(container_name, blob_name):
    """
    Returned keys:

    criticality_index (0-5):
        Higher means the blob is more important.

    has_historical_links (bool):
        True if this blob is considered to have some archival value
        (e.g. referenced by historical reports, logs, etc.).

    days_since_last_access (int or None):
        Number of days since this blob was last read, based on the mock history. None means "no reads in our history".

    human_trigger_index (0-5):
        Higher means reads are more likely to be driven directly by user actions (clicking / manual downloads).

    planned_activities_6m (bool):
        Whether we expect this blob to be used in the next 6 months. The probability depends on the hot/cool/cold/archive profile.

    media_relevance (0-5):
        Rough estimate of how important the blob is in terms of content
        (e.g. key video, image, document, etc.).
    """

    rng = _rng_for_blob(container_name, blob_name)
    profile = _profile_for_blob(container_name, blob_name)

    # Importance from 0 to 5.
    criticality_index = rng.randint(0, 5)

    # About a quarter of blobs get marked as "historical".
    has_historical_links = rng.random() < 0.25

    # Now tie "last access" to the fake access history above.
    now = datetime.now(timezone.utc)
    last_accessed_on, total_reads, _history = get_mock_access_window(
        container_name=container_name,
        blob_name=blob_name,
        window_days=MAX_HISTORY_DAYS,
    )

    # If the blob had at least one read at some point in the history, compute how many days ago that was.
    if last_accessed_on is not None:
        delta = now - last_accessed_on
        days_since_last_access = delta.days

        # As a small safety net, clamp negative values to zero.
        # Negative values would only happen if clocks are strange. (which happened before)
        if days_since_last_access < 0:
            days_since_last_access = 0
    else:
        # Blob has no reads
        days_since_last_access = None

    # Human-trigger index
    human_trigger_index = rng.randint(0, 5)

    # Planned activities is more likely if the profile is "hot" or "cool", and less likely for "cold" and "archive".
    if profile == "hot":
        planned_prob = 0.7
    elif profile == "cool":
        planned_prob = 0.4
    elif profile == "cold":
        planned_prob = 0.15
    else:
        # archive profile
        planned_prob = 0.05

    planned_activities_6m = rng.random() < planned_prob

    # How "relevant" the blob is in terms of content/value.
    media_relevance = rng.randint(0, 5)

    # Return a dictionary because it's easy to unpack later
    # using **meta in the tiering code.
    return {
        "criticality_index": criticality_index,
        "has_historical_links": has_historical_links,
        "days_since_last_access": days_since_last_access,
        "human_trigger_index": human_trigger_index,
        "planned_activities_6m": planned_activities_6m,
        "media_relevance": media_relevance,
    }
