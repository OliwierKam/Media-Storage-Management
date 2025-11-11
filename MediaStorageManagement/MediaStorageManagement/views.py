# Django imports
from django.shortcuts import render
from django.conf import settings
from django.contrib import messages

# Django app packages
from utils import pricing, changefeed

# Other
from datetime import datetime, timezone

# Azure imports
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceExistsError, ClientAuthenticationError, HttpResponseError, ResourceNotFoundError

# Authorise access to data in azure
account_url = settings.AZURE_STORAGE_ACCOUNT_URL
default_credential = DefaultAzureCredential()
blob_service_client = BlobServiceClient(account_url, credential=default_credential)

# ----- HELPERS -----

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

# Classify usage from Azure's last access time
def usage_bucket(last_accessed_on):
    """
    - <= 30 days: Hot usage
    - 31–180 days: Cool usage
    - > 180 days or None: Cold usage
    """
    if not last_accessed_on:
        return "Cold"
    days = (datetime.now(timezone.utc) - last_accessed_on).days
    if days <= 30:
        return "Hot"
    if days <= 180:
        return "Cool"
    return "Cold"

# ----- VIEWS -----

# homepage template
def homepage(request):
    # Check form submission
    if request.method == "POST":

        context = {}

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
            
            container_client = blob_service_client.get_container_client(container=container_name)
            
            # Try to get list of blobs
            try:
                blob_list = list(container_client.list_blobs())
                container = container_client.get_container_properties()

                # Attach MVP cost & usage classification to each blob row
                for b in blob_list:
                    # capacity £/mo (size × tier per-GB-month)
                    cap = pricing.estimate_capacity_month(size_bytes=b.size, tier=b.blob_tier)

                    # usage bucket based on Azure last access time
                    bucket = usage_bucket(getattr(b, "last_accessed_on", None))

                    # MVP keeps usage £/mo as 0.00 for now; you can change per-bucket add-ons later
                    usage_cost = 0.0

                    # attach for template
                    setattr(b, "usage_bucket", bucket)
                    setattr(b, "est_capacity_month", cap)
                    setattr(b, "est_usage_month", usage_cost)
                    setattr(b, "est_total_month", cap + usage_cost)

                context = {
                    'blob_list': blob_list,
                    'container': container
                }

                return render(request, "homepage.html", context)
            except ResourceNotFoundError:
                messages.error(request, "Container not found.")
            except ClientAuthenticationError:
                messages.error(request, "Not authorized. Check Azure login.")
            except HttpResponseError:
                messages.error(request, "Unexpected Azure error during upload.")          
        
    return render(request, "homepage.html")

# blob_info template
def blob_info(request, container, blob):
    # Clients
    blob_client = blob_service_client.get_blob_client(container=container, blob=blob)
    container_client = blob_service_client.get_container_client(container)

    # Properties from Azure
    props = blob_client.get_blob_properties()
    container_props = container_client.get_container_properties()

    # Tier (prefer blob_tier, fall back to access_tier, default Hot)
    tier_raw = getattr(props, "blob_tier", None) or getattr(props, "access_tier", None) or "Hot"
    tier_norm = pricing._tier(tier_raw)

    # Size & unit price
    size_bytes = int(getattr(props, "size", 0))
    size_gb = size_bytes / pricing.BYTES_PER_GB
    unit_price = pricing.PRICE_PER_GB_MONTH[tier_norm]

    # Capacity estimate (£/mo)
    est_capacity = pricing.estimate_capacity_month(size_bytes=size_bytes, tier=tier_norm)

    # Usage bucket from Azure Last Access Time
    last_accessed = getattr(props, "last_accessed_on", None)
    days_since_access = (datetime.now(timezone.utc) - last_accessed).days if last_accessed else None
    bucket = usage_bucket(last_accessed)

    # Azure Change Feed write-side counts (create/overwrite/metadata/tier/delete)
    change_counts = changefeed.get_write_counts_for_blob(
        account_url=settings.AZURE_STORAGE_ACCOUNT_URL,
        container=container,
        blob_path=blob,
        days=30, # adjust the window of days for lookback.
    )

    est_total = est_capacity

    context = {
        # original objects
        "blob": props,
        "container": container_props,

        # identifiers
        "blob_name": blob,
        "container_name": container,

        # timestamps / usage label
        "last_modified": getattr(props, "last_modified", None),
        "last_accessed_on": last_accessed,
        "creation_time": getattr(props, "creation_time", None),
        "days_since_access": days_since_access,
        "usage_bucket": bucket,

        # size & tier & pricing inputs
        "size_bytes": size_bytes,
        "size_gb": size_gb,
        "tier_raw": tier_raw,
        "tier_norm": tier_norm,
        "unit_price": unit_price,

        # change feed counts
        "cf_created": change_counts["created"],
        "cf_updated": change_counts["updated"],
        "cf_deleted": change_counts["deleted"],

        # estimates (£/mo)
        "est_capacity_month": est_capacity,
        "est_usage_month": est_usage,
        "est_total_month": est_total,
    }

    return render(request, "blob_info.html", context)
