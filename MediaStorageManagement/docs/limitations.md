# Limitations

# 1. No Real Per-Blob Access Logs
HNS-enabled accounts cannot emit GetBlob logs to Log Analytics.
Mock usage is used instead. Could workaround using a seperate service that collects logs.

# 2. Azure Students Restrictions
No Microsoft.CDN or FrontDoor cannot capture access logs indirectly.

# 3. No Historical Backfill
Azure only logs after diagnostics enabled.

# 4. Huge Containers
Performance constraints for containers with millions of blobs. It is possible to avoid loading all blobs, however this would disable container-wide cost metrics.
