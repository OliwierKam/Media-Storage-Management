# utils/changefeed.py
from datetime import datetime, timedelta, timezone
from typing import Dict, Any
from azure.identity import DefaultAzureCredential
from azure.storage.blob.changefeed import ChangeFeedClient

def _val(e: Any, *names: str):
    # Return attribute or dict key value, whichever exists first.
    for n in names:
        if hasattr(e, n):
            return getattr(e, n)
        if isinstance(e, dict) and n in e:
            return e[n]
    return None

def get_write_counts_for_blob(
    account_url: str,
    container: str,
    blob_path: str,
    days: int = 30, # This is the default. Change value in views (blob_info)
) -> Dict[str, int]:
    
    # Count write-side Change Feed events for one blob in the last N days.
    # - created: BlobCreated / BlobSnapshotCreated
    # - updated: BlobPropertiesUpdated / BlobTierChanged / (other non-delete)
    # - deleted: BlobDeleted

    cred = DefaultAzureCredential()
    cf = ChangeFeedClient(account_url=account_url, credential=cred)

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)

    created = updated = deleted = 0

    # Iterate events in the time window
    for evt in cf.list_changes(start_time=start, end_time=end):
        subject = _val(evt, "subject")
        etype = _val(evt, "event_type", "eventType") or ""

        if not subject or f"/containers/{container}/" not in subject or "/blobs/" not in subject:
            continue

        path = subject.split("/blobs/", 1)[1]
        if path != blob_path:
            continue

        if etype in ("BlobDeleted",):
            deleted += 1
        elif etype in ("BlobCreated", "BlobSnapshotCreated"):
            created += 1
        else:
            # Count tier changes, metadata/properties updates, and other non-delete events as "updated"
            updated += 1

    return {"created": created, "updated": updated, "deleted": deleted}
