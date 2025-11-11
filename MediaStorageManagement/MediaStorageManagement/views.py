# Django imports
from django.shortcuts import render
from django.conf import settings
from django.contrib import messages
from django.urls import reverse
from urllib.parse import urlencode

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

# Page blobs efficiently with continuation tokens
def list_blobs_page(container_client, prefix: str | None, continuation_token: str | None, page_size: int = 100):
    pager = container_client.list_blobs(
        name_starts_with=prefix or None,
        results_per_page=page_size,
    ).by_page(continuation_token)
    page = next(pager, [])
    blobs = list(page)
    next_token = pager.continuation_token  # None if no more pages
    return blobs, next_token

# Build a short key that identifies a paging universe for session storage
def _page_key(container_name: str, prefix: str | None, page_size: int) -> str:
    # small normalized key to partition token stacks
    return f"{container_name}||{prefix or ''}||{page_size}"

# Ensure a token stack exists in session for this key
def _get_stack(request, key: str):
    stacks = request.session.get("ct_stacks", {})
    stack = stacks.get(key)
    if stack is None:
        stack = [""]  # page 1 start marker (token for first page is empty/None)
        stacks[key] = stack
        request.session["ct_stacks"] = stacks
    return stack

def _set_stack(request, key: str, stack):
    stacks = request.session.get("ct_stacks", {})
    stacks[key] = stack
    request.session["ct_stacks"] = stacks

# ----- VIEWS -----

# homepage template
def homepage(request):
    # Handle POST actions (create/upload) and let listing flow through to GET for paging
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
            except HttpResponseError:
                messages.error(request, "Unexpected Azure error while creating the container.")
            else:
                messages.success(request, f"Container '{container_name}' created.")
            return render(request, "homepage.html")
            
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
            return render(request, "homepage.html")

    # Scalable listing via GET (Azure-native cursor paging; session-backed prev/next)
    if request.method == "GET" and ("container_name" in request.GET):
        container_name = request.GET.get("container_name", "").strip()

        # Check validiy of name
        error = check_container_name(container_name)

        if error:
            messages.error(request, error)
            return render(request, "homepage.html")
        
        prefix = request.GET.get("prefix") or None

        # configurable page size; clamp to safe range
        try:
            page_size = int(request.GET.get("page_size", 100))
        except ValueError:
            page_size = 100
        page_size = max(10, min(5000, page_size))

        # requested page (1-based)
        try:
            p = int(request.GET.get("p", "1") or "1")
        except ValueError:
            p = 1
        if p < 1:
            p = 1

        key = _page_key(container_name, prefix, page_size)
        stack = _get_stack(request, key)

        # If this is a new query (first arrival without explicit p) reset stack
        if "container_name" in request.GET and "p" not in request.GET:
            stack = [""]  # reset to start
            _set_stack(request, key, stack)

        # If navigating forward beyond known tokens, we step from last known token
        current_index = min(p - 1, len(stack) - 1)
        start_token = stack[current_index] or None

        container_client = blob_service_client.get_container_client(container=container_name)

        try:
            # Fetch ONE Azure page starting at start_token
            blob_list, next_ct = list_blobs_page(container_client, prefix, start_token, page_size=page_size)
            container = container_client.get_container_properties()

            # If we navigated to a new page (exactly one past the end of known stack) and Azure gave next_ct, append it
            if (p == len(stack)) and next_ct:
                stack.append(next_ct or "")
                _set_stack(request, key, stack)

            # Annotate only current page rows
            now_utc = datetime.now(timezone.utc)

            for b in blob_list:
                cap = pricing.estimate_capacity_month(size_bytes=b.size, tier=b.blob_tier)
                last_acc = getattr(b, "last_accessed_on", None)
                bucket = usage_bucket(last_acc)

                days_since = (now_utc - last_acc).days if last_acc else None
                setattr(b, "usage_bucket", bucket)
                setattr(b, "est_capacity_month", cap)
                setattr(b, "days_since_access", days_since)

            # Build Prev/Next URLs (short; no giant tokens in URL)
            base_params = {
                "container_name": container_name,
                "page_size": page_size,
            }
            if prefix:
                base_params["prefix"] = prefix

            prev_url = None
            if p > 1:
                params_prev = base_params.copy()
                params_prev["p"] = p - 1
                prev_url = f"{reverse('homepage')}?{urlencode(params_prev)}"

            next_url = None
            if next_ct:  # only if Azure says there is a next page
                params_next = base_params.copy()
                params_next["p"] = p + 1
                next_url = f"{reverse('homepage')}?{urlencode(params_next)}"

            context = {
                'blob_list': blob_list,
                'container': container,
                'container_name': container_name,
                'prefix': (prefix or ""),
                'page_size': page_size,

                # paging UI
                'page_num': p,
                'prev_url': prev_url,
                'next_url': next_url,
                'has_next': bool(next_ct),
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
    try:
        change_counts = changefeed.get_write_counts_for_blob(
            account_url=settings.AZURE_STORAGE_ACCOUNT_URL,
            container=container,
            blob_path=blob,
            days=30, # adjust the window of days for lookback.
        )
    except Exception:
        change_counts = {"created": "—", "updated": "—", "deleted": "—"}

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
        "est_total_month": est_total,
    }

    return render(request, "blob_info.html", context)
