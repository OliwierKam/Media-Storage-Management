# Django imports
from django.shortcuts import render
from django.http import HttpResponse
from django.conf import settings
from django.contrib import messages

# Azure imports
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, BlobClient, ContainerClient
from azure.core.exceptions import ResourceExistsError, ClientAuthenticationError, HttpResponseError

# Authorise access to data in azure
account_url = settings.AZURE_STORAGE_ACCOUNT_URL
default_credential = DefaultAzureCredential()
blob_service_client = BlobServiceClient(account_url, credential=default_credential)

def homepage(request):
    # Check container creation form submission 
    if request.method == "POST":
        container_name = request.POST.get('container_name')

        # The following are required by Azure
        container_name.strip().lower()

        if not (3 <= len(container_name) <= 63):
            messages.error(request, "Container name must be between 3-63 characters.")
            return render(request, "homepage.html")
        
        allowed_characters = set("abcdefghijklmnopqrstuvwxyz0123456789-")
        if any(x not in allowed_characters for x in container_name):
            messages.error(request, "Only lowercase letters, numbers, and hyphens allowed.")
            return render(request, "homepage.html")
        
        if not (container_name[0].isalnum() and container_name[-1].isalnum()):
            messages.error(request, "Start and end must be alphanumeric.")
            return render(request, "homepage.html")
        
        if "--" in container_name:
            messages.error(request, "No consecutive hyphens.")
            return render(request, "homepage.html")
        
        # Try to create the container if checks pass
        try:
            blob_service_client.create_container(container_name)
        except ResourceExistsError:
            messages.info(request, f"Container '{container_name}' already exists.")
        except ClientAuthenticationError:
            messages.error(request, "Not authorized. Check RBAC on the storage account or your Azure login/subscription.")
        except HttpResponseError as ex:
            messages.error(request, "Unexpected Azure error while creating the container.")
        else:
            messages.success(request, f"Container '{container_name}' created.")
        
    return render(request, "homepage.html")