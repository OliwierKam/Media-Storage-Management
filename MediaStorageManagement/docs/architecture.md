# System Architecture

This document describes the Django project structure and how each component interacts with Azure Blob Storage, the pricing engine, and the tier optimisation algorithm.

# Core Components

# Django Web Layer
- Renders UI (listing, modals, charts)
- Processes GET filters (container, prefix, pagination)
- Processes POST actions (tier changes)
- Calls annotation pipeline for each blob

# Azure Integration
The app uses:

- 'BlobServiceClient' (module-wide instance)
- 'DefaultAzureCredential' (supports local dev + production)

# Pricing Engine (pricing.py)
Responsible for:

- Capacity cost (per GB/month)
- Read operation cost (per 10k reads)
- Combined cost
- Normalisation of storage tier input
- Full raw cost table per blob

# Mock Usage Engine (mock_usage.py)
Generates deterministic usage patterns:

- Last 365 days of reads
- Per-window summaries (30, 180, 365 days)
- Business metadata simulation:
  - Criticality
  - Historical linkage
  - Relevance
  - Human-trigger likelihood
  - Planned future activity

# Template Layer

The UI includes:

- Blob list table
- Per-blob modal suggestion
- Bulk suggestion modal
- Chart.js cost visualisation
- Pagination
- Prefix filtering

Templates: homepage.html, blob_info.html

# Tests

Located in 'tests.py':

- Validates container name rules
- Validates tier change flow
- Validates creation/upload handling
- Uses mocks (`patch`) to avoid real Azure calls

The tests it contains at the moment are an example. This file should get populated once the system is finalised.

# Deployment Considerations

- Works with Azure CLI, Managed Identity, VSCode cloud identity
- Does not require storing secrets locally
- Can run as a container or Azure App Service
- Stateless — Azure acts as single datastore

Should be deployed with a third party software that collects Azure blob data in mind. At the moment, only mocked data is being fed as input.
