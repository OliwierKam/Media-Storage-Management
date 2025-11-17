# views.py

# Django imports
from django.shortcuts import render
from django.conf import settings
from django.contrib import messages
from django.urls import reverse
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from urllib.parse import urlencode

# Django app packages
from utils import pricing
from utils import mock_usage

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
            except ClientAuthenticationError:  # Pops if changes aren't authenticated.
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

    # Scalable listing via GET (now using Django Paginator)
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

        container_client = blob_service_client.get_container_client(container=container_name)

        try:
            # Container props for heading
            container = container_client.get_container_properties()

            # Get all blobs (optionally filtered by prefix)
            blob_iter = container_client.list_blobs(name_starts_with=prefix or None)
            blob_list_all = list(blob_iter)

            # Simple paginator
            paginator = Paginator(blob_list_all, page_size)

            try:
                page_obj = paginator.page(p)
            except PageNotAnInteger:
                page_obj = paginator.page(1)
                p = 1
            except EmptyPage:
                page_obj = paginator.page(paginator.num_pages)
                p = paginator.num_pages

            # Annotate only current page rows
            for b in page_obj.object_list:
                # capacity estimate for this blob
                cap = pricing.estimate_capacity_month(size_bytes=b.size, tier=b.blob_tier)

                # mock reads in last 30 days (used as "monthly" usage)
                _last_30, total_30, _hist_30 = mock_usage.get_mock_access_window(
                    container_name=container_name,
                    blob_name=b.name,
                    window_days=30,
                )

                # mock reads in last 180 days
                _last_180, total_180, _hist_180 = mock_usage.get_mock_access_window(
                    container_name=container_name,
                    blob_name=b.name,
                    window_days=180,
                )

                # mock reads in last 365 days
                _last_365, total_365, _hist_365 = mock_usage.get_mock_access_window(
                    container_name=container_name,
                    blob_name=b.name,
                    window_days=365,
                )

                # read operation cost per month (based on last 30 days)
                read_cost = pricing.estimate_read_cost_month(
                    reads_30_days=total_30,
                    tier=b.blob_tier,
                )

                # total estimated cost = capacity + read operations
                total_cost = cap + read_cost

                # attach values for template
                setattr(b, "access_30d", total_30)
                setattr(b, "access_180d", total_180)
                setattr(b, "access_365d", total_365)
                setattr(b, "est_capacity_month", cap)
                setattr(b, "est_read_month", read_cost)
                setattr(b, "est_total_month", total_cost)

            # Build Prev/Next URLs (short; no tokens)
            base_params = {
                "container_name": container_name,
                "page_size": page_size,
            }
            if prefix:
                base_params["prefix"] = prefix

            prev_url = None
            if page_obj.has_previous():
                params_prev = base_params.copy()
                params_prev["p"] = page_obj.previous_page_number()
                prev_url = f"{reverse('homepage')}?{urlencode(params_prev)}"

            next_url = None
            if page_obj.has_next():
                params_next = base_params.copy()
                params_next["p"] = page_obj.next_page_number()
                next_url = f"{reverse('homepage')}?{urlencode(params_next)}"

            context = {
                'blob_list': page_obj.object_list,
                'container': container,
                'container_name': container_name,
                'prefix': (prefix or ""),
                'page_size': page_size,

                # paging UI
                'page_num': page_obj.number,
                'prev_url': prev_url,
                'next_url': next_url,
                'has_next': page_obj.has_next(),
                'paginator': paginator,
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

    # mock reads in last 30/180/365 days
    _last_30, total_30, _hist_30 = mock_usage.get_mock_access_window(
        container_name=container,
        blob_name=blob,
        window_days=30,
    )
    _last_180, total_180, _hist_180 = mock_usage.get_mock_access_window(
        container_name=container,
        blob_name=blob,
        window_days=180,
    )
    _last_365, total_365, _hist_365 = mock_usage.get_mock_access_window(
        container_name=container,
        blob_name=blob,
        window_days=365,
    )

    # read operation cost per month (based on last 30 days)
    est_read_month = pricing.estimate_read_cost_month(
        reads_30_days=total_30,
        tier=tier_norm,
    )

    # total cost = capacity + reads
    est_total = est_capacity + est_read_month

    context = {
        # original objects
        "blob": props,
        "container": container_props,

        # identifiers
        "blob_name": blob,
        "container_name": container,

        # timestamps
        "last_modified": getattr(props, "last_modified", None),
        "creation_time": getattr(props, "creation_time", None),

        # size & tier & pricing inputs
        "size_bytes": size_bytes,
        "size_gb": size_gb,
        "tier_raw": tier_raw,
        "tier_norm": tier_norm,
        "unit_price": unit_price,

        # estimates (£/mo)
        "est_capacity_month": est_capacity,
        "est_read_month": est_read_month,
        "est_total_month": est_total,

        # mock read counts
        "access_30d": total_30,
        "access_180d": total_180,
        "access_365d": total_365,
    }

    return render(request, "blob_info.html", context)
