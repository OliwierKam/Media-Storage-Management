BYTES_PER_GB = 1024**3

"""
Note: Check later if it is possible to get these from an Azure package instead)
https://azure.microsoft.com/en-us/pricing/details/storage/blobs/

Region: Germany West Central
Redundancy: RA GRS
File Structure: Hierarchical Namespace

Data storage prices pay-as-you-go: First 50 terabyte (TB)/month (£ per GB)
"""
PRICE_PER_GB_MONTH = {
    "Hot":     0.0371,
    "Cool":    0.01889,
    "Cold":    0.00763,
    "Archive": 0.00211,
}

"""
The following function estimates a blob's current cost per month in its tier.

days_in_month is currently set to 30 for an average
(although for more accurate results, this can be acjusted to be 28/29/30/31 depending on the month)

days_in_tier states how long the blob has been in this tier for this month. This can also be adjusted for accuracy.

At the moment, I believe 30 for both factors is the correct number, as we are tring to find the average cost for a blob in its current tier.
"""
def estimate_capacity_month(size_bytes: int, tier: str, days_in_month: int = 30, days_in_tier: int = 30) -> float:
    # normalize tier (Blob SDK may give enums/None)
    t = (tier or "Hot")
    if not isinstance(t, str):
        t = str(t)
    # Map enum-like values to strings if needed
    if "Hot" in t: t = "Hot"
    elif "Cool" in t: t = "Cool"
    elif "Cold" in t: t = "Cold"
    elif "Archive" in t: t = "Archive"
    else: t = "Hot"

    price = PRICE_PER_GB_MONTH[t]
    size_gb = size_bytes / BYTES_PER_GB
    return size_gb * price * (days_in_tier / days_in_month)
