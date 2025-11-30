# Setup Guide

This guide describes how to set up the project locally or in a development environment.

# 1. Requirements

- Python 3.11+
- Django
- Azure CLI ('az')
- Azure account with Blob Storage
- Azure Identity permissions

# 2. Installation

# Install dependencies

Required packages include:

- django
- azure-identity
- azure-storage-blob

# 3. Azure Setup

# Login
bash:
az login

If CLI missing:

https://aka.ms/installazurecliosx

# Configure Azure Storage

Enable:

- Access Tracking: (for last access, uneccesary if there is a third party software tracking access)
Azure Portal → Storage Account → Data Management → Lifecycle Management

# 4. Django Settings

In 'settings.py':

AZURE_STORAGE_ACCOUNT_NAME = "yourname"
AZURE_STORAGE_ACCOUNT_URL = f"https://{AZURE_STORAGE_ACCOUNT_NAME}.blob.core.windows.net"
AZURE_REGION = "your region"

# 5. Run Server

bash:
python manage.py runserver

Visit:

http://127.0.0.1:8000/homepage/
