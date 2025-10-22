# Media-Storage-Management
Media storage management web application integrated with Azure Blob Storage.

# Set Up on Local Machine

Required installations using PIP:

azure-identity
azure-storage-blob

Follow https://learn.microsoft.com/en-us/python/api/overview/azure/identity-readme?view=azure-python for set-up guide

NOTE:

If 'az login' doesn't work, install CLI via https://learn.microsoft.com/en-us/cli/azure/install-azure-cli-macos?view=azure-cli-latest


In order to enable 'last accessed tracking' for your account:

Find storage account on Azure
>Data management
>Lifecycle management
>Tick 'Enable access tracking'

NOTE:

This incurs an additional cost but is useful to know how often a file is accessed.
It may take a few hours for the data to get populated. May not work at the start.

# Views

Is responsbile for the basic logic and communication between Frontend HTML files and Azure Cloud Service

# Settings

The following is for the Azure account:
AZURE_STORAGE_ACCOUNT_URL = https://<account>.blob.core.windows.net