# Media Storage Management

This project is a Django-based application designed to intelligently analyse, classify, and optimise the storage tier of media files in Azure Blob Storage.
It determines whether each blob should stay in Hot, Cool, Cold, or Archive storage, balancing:

- Fast access to important media
- Cost optimisation
- Operational constraints
- Business context and metadata
- Usage patterns

The system integrates with Azure Blob Storage using 'DefaultAzureCredential', allowing it to run locally, on an internal server, or in the cloud with no code changes.

The heart of the project is the 'tier optimisation algorithm', built to model real-world behaviour and limitations of Azure’s pricing model.

# Intelligent Blob Tier Recommendation
An algorithm recommends the optimal storage tier for each blob.

Inputs include:

- Blob size
- Historical access patterns
- Predicted future access
- Criticality (0–5)
- Media relevance (0–5)
- Human-trigger likelihood (0–5)
- Planned future activity
- Days since creation / last access
- Historical importance

Outputs include:

- Recommended Tier
- Predicted monthly cost (current tier)
- Predicted monthly cost (optimal tier)
- Estimated savings per month

# Bulk or Single Blob Tier Application
The UI provides:

- One-click single-tier change modals
- Bulk application using checkboxes
- Automatic refresh using PRG pattern

# Cost Visualisation  
Chart.js graphs show current vs optimised monthly spend:

- Globally (all containers)
- Per-container

Useful for business justification and optimisation validation.

# Fully Mocked Usage Engine
Because HNS-enabled accounts do not emit access logs, the system includes a deterministic mock usage generator to simulate future integrations with external telemetry sources.

# Azure-Native Architecture
The app uses:

- Azure Blob Storage
- Azure Identity ('DefaultAzureCredential')

Designed so it can later accept:

- Usage logs
- Business metadata from external systems

# Documentation

Full documentation is located in the 'docs' folder

# Running the Application

1. Install Dependencies

Required packages include:

- Django
- azure-identity
- azure-storage-blob

2. Configure Azure Settings

Follow https://learn.microsoft.com/en-us/python/api/overview/azure/identity-readme?view=azure-python for set-up guide

In order to enable 'last accessed tracking' for your account:

Find storage account on Azure
>Data management
>Lifecycle management
>Tick 'Enable access tracking'

NOTE:

This incurs an additional cost but is useful to know how often a file is accessed.
It may take a few hours for the data to get populated. May not work at the start.

Set these in 'settings.py':

AZURE_STORAGE_ACCOUNT_NAME = "YOUR_NAME"
AZURE_STORAGE_ACCOUNT_URL = f"https://{AZURE_STORAGE_ACCOUNT_NAME}.blob.core.windows.net"
AZURE_REGION = "YOUR_REGION"

3. Authenticate to Azure

'az login'

If 'az login' doesn't work, install CLI via https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-macos?view=azure-cli-lates

Or rely on managed identity when deployed.

4. Run Django

'python manage.py runserver'

# About the Algorithm

The core of this project is 'find_optimal_tier' — a configurable, weighted decision engine that:

- Computes raw capacity + read operation cost for each tier
- Builds a heat score to estimate expected usage
- Applies rules preventing unreasonable tier moves
- Applies penalties/discounts to simulate business behaviour
- Selects the tier with the lowest adjusted monthly cost
