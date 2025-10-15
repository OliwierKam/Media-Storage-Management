# Django imports
from django.shortcuts import render
from django.http import HttpResponse
from django.conf import settings
from django.contrib import messages

# Azure imports
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, BlobClient, ContainerClient
from azure.core.exceptions import ResourceExistsError, ClientAuthenticationError, HttpResponseError, ResourceNotFoundError

# Authorise access to data in azure
account_url = settings.AZURE_STORAGE_ACCOUNT_URL
default_credential = DefaultAzureCredential()
blob_service_client = BlobServiceClient(account_url, credential=default_credential)

# Verifies if container name satisfies Azure requirements
def check_container_name(container_name):

    # The following are required by Azure
    if not (3 <= len(container_name) <= 63):
        return "Container name must be between 3-63 characters."
    
    allowed_characters = set("abcdefghijklmnopqrstuvwxyz0123456789-")
    if any(x not in allowed_characters for x in container_name):
        return "Only lowercase letters, numbers, and hyphens allowed."
    
    if not (container_name[0].isalnum() and container_name[-1].isalnum()):
        return "Start and end must be alphanumeric."
    
    if "--" in container_name:
        return "No consecutive hyphens."
    
    return None

# homepage template
def homepage(request):
    # Check form submission
    if request.method == "POST":

        # Check container creation
        if "create_container" in request.POST:
            container_name = request.POST.get('container_name')

            # Check validiy of name
            error = check_container_name(container_name)

            if error:
                messages.error(request, error)
                return render(request, "homepage.html")
            
            # Try to create the container if check passes
            try:
                blob_service_client.create_container(container_name)
            except ResourceExistsError:
                messages.info(request, f"Container '{container_name}' already exists.")
            except ClientAuthenticationError: # Pops if changes aren't authenticated.
                messages.error(request, "Not authorized. Check Azure login.")
            except HttpResponseError as ex:
                messages.error(request, "Unexpected Azure error while creating the container.")
            else:
                messages.success(request, f"Container '{container_name}' created.")
            
        # Check blob upload
        elif "upload_blob" in request.POST:

            # Check for file
            if "blob_file" not in request.FILES:
                messages.error(request, "Select a file to upload.")
                return render(request, "homepage.html")
            
            blob_file = request.FILES["blob_file"]
            blob_name = blob_file.name
            container_name = request.POST.get("container_name")

            # Check validiy of name
            error = check_container_name(container_name)

            if error:
                messages.error(request, error)
                return render(request, "homepage.html")
            
            # Create a blob client using the file name as the name for the blob
            blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_name)

            # Try to upload blob
            try:
                blob_client.upload_blob(blob_file, overwrite=True)
            except ResourceNotFoundError:
                messages.error(request, "Container not found.")
            except ClientAuthenticationError:
                messages.error(request, "Not authorized. Check Azure login.")
            except HttpResponseError:
                messages.error(request, "Unexpected Azure error during upload.")
            else:
                messages.success(request, f"Uploaded '{blob_name}' to '{container_name}'.")

        # Check listing blobs
        elif "list_blobs" in request.POST:
            container_name = request.POST.get("container_name")

            # Check validiy of name
            error = check_container_name(container_name)

            if error:
                messages.error(request, error)
                return render(request, "homepage.html")
            
            container = blob_service_client.get_container_client(container=container_name)
            
            # Try to list blobs
            try:
                blob_list = container.list_blobs()
                for blob in blob_list:
                    blob_name = blob.name
                    messages.success(request, f"{blob_name}")
            except ResourceNotFoundError:
                messages.error(request, "Container not found.")
            except ClientAuthenticationError:
                messages.error(request, "Not authorized. Check Azure login.")
            except HttpResponseError:
                messages.error(request, "Unexpected Azure error during upload.")          
        
    return render(request, "homepage.html")