# Usage Guide

This guide explains how to navigate the UI and use the system features.

# 1. Listing Blobs

Enter a container name to see:

- Blob name
- Size
- Tier
- Access counts (30, 180, 365 days)
- Estimated cost
- Optimal tier
- Expected savings

Filters available:

- Prefix filtering
- Adjustable page size
- Pagination

# 2. Blob Details Page

Shows:

- Identity
- Timestamps
- Size + GB conversion
- Pricing inputs
- Heat-related metadata
- Cost estimates
- Recommended tier
- Rationale

# 3. Charts

Two charts available:

- Global cost chart
- Per-container cost chart

Both compare:

- Current monthly cost
- Optimised monthly cost

# 4. Single Tier Change

Click "View suggested change" to open the modal.

Modal shows:

- Current tier
- Recommended tier
- Cost impact
- Bullet-point explanation
- Metadata used

# 5. Bulk Tier Change

Click "Show suggested tier changes".

Bulk modal includes:

- Select-all checkbox
- Per-row selections
- Full cost table
- Submit button to apply all at once

# 6. Error Handling

Covers:

- Invalid container name
- Missing files
- Azure authentication errors
- Blob not found
- Azure HTTP errors
