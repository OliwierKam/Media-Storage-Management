# Developer Reference

This file documents the most important modules and functions.

# 1. Views (views.py)

# homepage(request)
Central controller for:

- Blob listing
- Cost annotation
- Chart generation
- Tier changes
- Error handling
- Pagination

# annotate_blob_with_costs(container, blob)
Attaches:

- Access counts
- Cost estimates
- Optimal tier
- Savings
- Metadata

# change_blob_tier(container, blob, tier)
Calls Azure API:

blob_client.set_standard_blob_tier()

# check_container_name(name)
Validates Azure naming rules.

# 2. Pricing Engine (pricing.py)

Functions:

- estimate_capacity_month
- estimate_read_cost_month
- estimate_total_month
- _tier
- find_optimal_tier

# 3. Mock Usage Engine (mock_usage.py)

Functions:

- generate_mock_history
- get_mock_access_window
- get_mock_blob_metadata

All deterministic based on blob name hash.

# 4. Templates

- homepage.html - tables, modals, charts
- blob_info.html - detailed readout

Front-end JS:

- Bulk modal logic
- Single modal logic
- Chart.js with value label plugin

# 5. Tests (tests.py)

Covers:

- Container validation
- List actions
- Tier application
- File upload
- Error scenarios
- Azure mock patching
