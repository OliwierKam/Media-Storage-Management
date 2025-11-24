# Django imports
from django.shortcuts import render, redirect
from django.conf import settings
from django.contrib import messages
from django.urls import reverse
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from urllib.parse import urlencode
from datetime import datetime, timezone

# Django app packages
from utils import pricing
from utils import mock_usage

# Azure imports
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import (
    ResourceExistsError,
    ClientAuthenticationError,
    HttpResponseError,
    ResourceNotFoundError,
)

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


# Change tier for a single blob
def change_blob_tier(container_name: str, blob_name: str, new_tier: str):
    blob_client = blob_service_client.get_blob_client(
        container=container_name,
        blob=blob_name,
    )
    blob_client.set_standard_blob_tier(new_tier)


# Annotate a blob object with usage + cost + suggested tier
def annotate_blob_with_costs(container_name, blob_obj):
    # capacity estimate for this blob (using its current tier)
    cap = pricing.estimate_capacity_month(
        size_bytes=blob_obj.size,
        tier=blob_obj.blob_tier,
    )

    # mock reads in last 30 days
    _last_30, total_30, _hist_30 = mock_usage.get_mock_access_window(
        container_name=container_name,
        blob_name=blob_obj.name,
        window_days=30,
    )

    # mock reads in last 180 days
    _last_180, total_180, _hist_180 = mock_usage.get_mock_access_window(
        container_name=container_name,
        blob_name=blob_obj.name,
        window_days=180,
    )

    # mock reads in last 365 days (for display)
    _last_365, total_365, _hist_365 = mock_usage.get_mock_access_window(
        container_name=container_name,
        blob_name=blob_obj.name,
        window_days=365,
    )

    # mock reads across full available history for cost decision
    _last_all, total_all, _hist_all = mock_usage.get_mock_access_window(
        container_name=container_name,
        blob_name=blob_obj.name,
        window_days=mock_usage.MAX_HISTORY_DAYS,
    )

    # use full-history reads for cost comparison
    reads_for_cost = total_all

    # read operation cost based on full-history reads
    read_cost = pricing.estimate_read_cost_month(
        reads_count=reads_for_cost,
        tier=blob_obj.blob_tier,
    )

    # total estimated cost = capacity + read operations (current tier)
    total_cost = cap + read_cost

    # compute days since creation (for tier algorithm)
    creation_time = getattr(blob_obj, "creation_time", None)
    if creation_time is not None:
        now = datetime.now(timezone.utc)
        days_since_creation = max(0, (now - creation_time).days)
    else:
        days_since_creation = None

    # mocked business metadata for this blob (criticality, relevance, etc.)
    meta = mock_usage.get_mock_blob_metadata(
        container_name=container_name,
        blob_name=blob_obj.name,
    )
    meta["days_since_creation"] = days_since_creation

    # find optimal tier based on size, full-history reads, and metadata
    opt_tier, opt_total, _per_tier = pricing.find_optimal_tier(
        size_bytes=blob_obj.size,
        reads_count=reads_for_cost,
        **meta,
    )

    # potential saving if moved to optimal tier
    opt_saving = total_cost - opt_total

    # attach values for template
    setattr(blob_obj, "access_30d", total_30)
    setattr(blob_obj, "access_180d", total_180)
    setattr(blob_obj, "access_365d", total_365)
    setattr(blob_obj, "est_capacity_month", cap)
    setattr(blob_obj, "est_read_month", read_cost)
    setattr(blob_obj, "est_total_month", total_cost)
    setattr(blob_obj, "opt_tier", opt_tier)
    setattr(blob_obj, "opt_total_month", opt_total)
    setattr(blob_obj, "opt_saving_month", opt_saving)


# ----- VIEWS -----


def homepage(request):
    # Handle POST actions (create/upload/change tiers)
    if request.method == "POST":

        # Single blob: apply suggested tier
        if "apply_tier_single" in request.POST:
            container_name = request.POST.get("container_name", "").strip()
            blob_name = request.POST.get("blob_name", "")
            target_tier = request.POST.get("target_tier", "")

            # listing parameters to restore view
            prefix = request.POST.get("prefix", "").strip()
            page_size = request.POST.get("page_size", "").strip()
            page_num = request.POST.get("page_num", "").strip()

            error = check_container_name(container_name)
            if error:
                messages.error(request, error)
            elif not blob_name or not target_tier:
                messages.error(request, "Missing blob name or target tier.")
            else:
                try:
                    change_blob_tier(container_name, blob_name, target_tier)
                except ResourceNotFoundError:
                    messages.error(request, "Blob or container not found while changing tier.")
                except ClientAuthenticationError:
                    messages.error(request, "Not authorized. Check Azure login.")
                except HttpResponseError:
                    messages.error(request, "Unexpected Azure error while changing tier.")
                else:
                    messages.success(request, f"Tier for '{blob_name}' changed to {target_tier}.")

            # redirect back to the same listing (PRG pattern)
            params = {"container_name": container_name}
            if prefix:
                params["prefix"] = prefix
            if page_size:
                params["page_size"] = page_size
            if page_num:
                params["p"] = page_num

            url = reverse("homepage")
            if params:
                url = f"{url}?{urlencode(params)}"
            return redirect(url)

        # Bulk apply from popup
        if "apply_tier_bulk" in request.POST:
            container_name = request.POST.get("container_name", "").strip()

            # listing parameters to restore view
            prefix = request.POST.get("prefix", "").strip()
            page_size = request.POST.get("page_size", "").strip()
            page_num = request.POST.get("page_num", "").strip()

            error = check_container_name(container_name)
            if error:
                messages.error(request, error)
            else:
                selected_items = request.POST.getlist("items")  # each "blob_name|tier"
                changed = 0

                for item in selected_items:
                    try:
                        blob_name, target_tier = item.split("|", 1)
                    except ValueError:
                        continue

                    try:
                        change_blob_tier(container_name, blob_name, target_tier)
                        changed += 1
                    except ResourceNotFoundError:
                        messages.error(request, f"{blob_name}: blob not found while changing tier.")
                    except ClientAuthenticationError:
                        messages.error(request, f"{blob_name}: not authorized while changing tier.")
                    except HttpResponseError:
                        messages.error(request, f"{blob_name}: Azure error while changing tier.")

                if changed > 0:
                    messages.success(request, f"Applied tier changes to {changed} blobs.")

            # redirect back to same listing
            params = {"container_name": container_name}
            if prefix:
                params["prefix"] = prefix
            if page_size:
                params["page_size"] = page_size
            if page_num:
                params["p"] = page_num

            url = reverse("homepage")
            if params:
                url = f"{url}?{urlencode(params)}"
            return redirect(url)

        # Check container creation
        if "create_container" in request.POST:
            container_name = request.POST.get("container_name", "").strip()

            error = check_container_name(container_name)
            if error:
                messages.error(request, error)
                return render(request, "homepage.html")
            
            try:
                blob_service_client.create_container(container_name)
            except ResourceExistsError:
                messages.info(request, f"Container '{container_name}' already exists.")
            except ClientAuthenticationError:
                messages.error(request, "Not authorized. Check Azure login.")
            except HttpResponseError:
                messages.error(request, "Unexpected Azure error while creating the container.")
            else:
                messages.success(request, f"Container '{container_name}' created.")
            return render(request, "homepage.html")
            
        # Check blob upload
        if "upload_blob" in request.POST:

            if "blob_file" not in request.FILES:
                messages.error(request, "Select a file to upload.")
                return render(request, "homepage.html")
            
            blob_file = request.FILES["blob_file"]
            blob_name = blob_file.name
            container_name = request.POST.get("container_name", "").strip()

            error = check_container_name(container_name)
            if error:
                messages.error(request, error)
                return render(request, "homepage.html")
            
            blob_client = blob_service_client.get_blob_client(
                container=container_name,
                blob=blob_name,
            )

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

    # ----- GET: listing + charts -----
    if request.method == "GET":
        # common query params
        container_name = request.GET.get("container_name", "").strip()
        prefix = request.GET.get("prefix") or None

        # flags to trigger chart calculations
        show_global_chart = request.GET.get("show_global_chart") == "1"
        show_container_chart = request.GET.get("show_container_chart") == "1"

        # page size
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

        # totals for charts
        global_current_total = None
        global_opt_total = None
        container_current_total = None
        container_opt_total = None

        # --- GLOBAL TOTALS: all containers, all blobs (only if asked) ---
        if show_global_chart:
            total_cur = 0.0
            total_opt = 0.0

            for c in blob_service_client.list_containers():
                c_name = c.name
                c_client = blob_service_client.get_container_client(c_name)
                for b in c_client.list_blobs():
                    # annotate each blob with costs
                    annotate_blob_with_costs(c_name, b)
                    total_cur += getattr(b, "est_total_month", 0.0)
                    total_opt += getattr(b, "opt_total_month", 0.0)

            global_current_total = total_cur
            global_opt_total = total_opt

        # --- CONTAINER LISTING ---
        if container_name:
            error = check_container_name(container_name)
            if error:
                messages.error(request, error)
                context = {
                    "container_name": container_name,
                    "prefix": prefix or "",
                    "page_size": page_size,
                    "show_global_chart": show_global_chart,
                    "show_container_chart": show_container_chart,
                    "global_current_total": global_current_total,
                    "global_opt_total": global_opt_total,
                    "container_current_total": container_current_total,
                    "container_opt_total": container_opt_total,
                }
                return render(request, "homepage.html", context)

            container_client = blob_service_client.get_container_client(
                container=container_name
            )

            try:
                # Container props for heading
                container = container_client.get_container_properties()

                # Get all blobs and filter prefix case-insensitively
                blob_iter = container_client.list_blobs()

                if prefix:
                    prefix_lower = prefix.lower()
                    blob_list_all = []
                    for b in blob_iter:
                        if b.name.lower().startswith(prefix_lower):
                            blob_list_all.append(b)
                else:
                    blob_list_all = list(blob_iter)

                # annotate all blobs in this container once
                for b in blob_list_all:
                    annotate_blob_with_costs(container_name, b)

                # per-container totals (all blobs)
                if show_container_chart:
                    container_current_total = sum(
                        getattr(b, "est_total_month", 0.0) for b in blob_list_all
                    )
                    container_opt_total = sum(
                        getattr(b, "opt_total_month", 0.0) for b in blob_list_all
                    )

                # paginator
                paginator = Paginator(blob_list_all, page_size)

                try:
                    page_obj = paginator.page(p)
                except PageNotAnInteger:
                    page_obj = paginator.page(1)
                    p = 1
                except EmptyPage:
                    page_obj = paginator.page(paginator.num_pages)
                    p = paginator.num_pages

                # collect suggestions only from the current page
                suggestions = []
                for b in page_obj.object_list:
                    if getattr(b, "opt_tier", None) and b.opt_tier != b.blob_tier:
                        suggestions.append(b)

                # Build Prev/Next URLs
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
                    "blob_list": page_obj.object_list,
                    "container": container,
                    "container_name": container_name,
                    "prefix": (prefix or ""),
                    "page_size": page_size,

                    # paging UI
                    "page_num": page_obj.number,
                    "prev_url": prev_url,
                    "next_url": next_url,
                    "has_next": page_obj.has_next(),
                    "paginator": paginator,

                    # suggested changes (for popup)
                    "suggestions": suggestions,

                    # chart flags + totals
                    "show_global_chart": show_global_chart,
                    "show_container_chart": show_container_chart,
                    "global_current_total": global_current_total,
                    "global_opt_total": global_opt_total,
                    "container_current_total": container_current_total,
                    "container_opt_total": container_opt_total,
                }

                return render(request, "homepage.html", context)

            except ResourceNotFoundError:
                messages.error(request, "Container not found.")
            except ClientAuthenticationError:
                messages.error(request, "Not authorized. Check Azure login.")
            except HttpResponseError:
                messages.error(request, "Unexpected Azure error during listing.")

        # GET with no container_name: maybe just global chart
        base_context = {
            "container_name": container_name,
            "prefix": prefix or "",
            "page_size": page_size,
            "show_global_chart": show_global_chart,
            "show_container_chart": show_container_chart,
            "global_current_total": global_current_total,
            "global_opt_total": global_opt_total,
            "container_current_total": container_current_total,
            "container_opt_total": container_opt_total,
        }
        return render(request, "homepage.html", base_context)

    # default
    return render(request, "homepage.html")


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

    # full-history reads for cost decision
    _last_all, total_all, _hist_all = mock_usage.get_mock_access_window(
        container_name=container,
        blob_name=blob,
        window_days=mock_usage.MAX_HISTORY_DAYS,
    )
    reads_for_cost = total_all

    # read operation cost (using full-history count)
    est_read_month = pricing.estimate_read_cost_month(
        reads_count=reads_for_cost,
        tier=tier_norm,
    )

    # total cost = capacity + reads
    est_total = est_capacity + est_read_month

    # compute days since creation (for tier algorithm)
    creation_time = getattr(props, "creation_time", None)
    if creation_time is not None:
        now = datetime.now(timezone.utc)
        days_since_creation = max(0, (now - creation_time).days)
    else:
        days_since_creation = None

    # mocked metadata for this blob
    meta = mock_usage.get_mock_blob_metadata(
        container_name=container,
        blob_name=blob,
    )
    meta["days_since_creation"] = days_since_creation

    # optimal tier and cost based on size + full-history reads + metadata
    opt_tier, opt_total, opt_per_tier = pricing.find_optimal_tier(
        size_bytes=size_bytes,
        reads_count=reads_for_cost,
        **meta,
    )
    opt_saving = est_total - opt_total

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

        # estimates (£/mo) for current tier
        "est_capacity_month": est_capacity,
        "est_read_month": est_read_month,
        "est_total_month": est_total,

        # optimal tier suggestion
        "opt_tier": opt_tier,
        "opt_total_month": opt_total,
        "opt_saving_month": opt_saving,

        # mock read counts for display
        "access_30d": total_30,
        "access_180d": total_180,
        "access_365d": total_365,
    }

    return render(request, "blob_info.html", context)
