# Media-Storage-Management
Media storage management web application integrated with Azure Blob Storage.

# Set Up on Local Machine

Required installations using PIP: (py -m pip install ...)

azure-identity
azure-storage-blob
azure-monitor-query

Follow https://learn.microsoft.com/en-us/python/api/overview/azure/identity-readme?view=azure-python for set-up guide

NOTE:

If 'az login' doesn't work, install CLI via https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-macos?view=azure-cli-lates

---

In order to enable 'last accessed tracking' for your account:

Find storage account on Azure
>Data management
>Lifecycle management
>Tick 'Enable access tracking'

NOTE:

This incurs an additional cost but is useful to know how often a file is accessed.
It may take a few hours for the data to get populated. May not work at the start.

---

In order to enable blob change feed:

Find storage account on Azure
>Data management
>Data protection
>Enable blob change feed

NOTE:

Deleting feed logs after x amount of days is advised to minimise costs.
At the moment views only lists events in the past 30 days.
Similarly, log feed is set to delete after 30 days on Azure on my storage account.

# Views

Is responsbile for the basic logic and communication between Frontend HTML files and Azure Cloud Service

# Settings

The following is for the azure storage account name:
AZURE_STORAGE_ACCOUNT_NAME = "YOUR_NAME"

This gets automatically filled in the URL:
AZURE_STORAGE_ACCOUNT_URL = f"https://{AZURE_STORAGE_ACCOUNT_NAME}.blob.core.windows.net"

Region of your Account:
AZURE_REGION = "YOUR REGION"

The GUID can be found under "Workspace ID" of your workspace:
LOG_ANALYTICS_WORKSPACE_ID = "WORKSPACE_GUID"