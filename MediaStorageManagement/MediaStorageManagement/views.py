# Django imports
from django.shortcuts import render, redirect
from django.conf import settings
from django.contrib import messages
from django.urls import reverse
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from urllib.parse import urlencode
from datetime import datetime, timezone

# Local utility modules that hold pricing and mock usage logic
from utils import pricing
from utils import mock_usage

# Azure SDK imports
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceExistsError, ClientAuthenticationError, HttpResponseError, ResourceNotFoundError

# AZURE CLIENT INITIALISATION

# A single BlobServiceClient is built for the whole module.
# This uses the account URL from Django settings and the default Azure credentials

account_url = settings.AZURE_STORAGE_ACCOUNT_URL
default_credential = DefaultAzureCredential()
blob_service_client = BlobServiceClient(account_url, credential=default_credential)

# HELPERS

# Validate a container name according to Azure rules.
def check_container_name(container_name: str) -> str | None:

    # Length must be between 3 and 63 characters, per Azure rules.
    if not (3 <= len(container_name) <= 63):
        return "Container name must be between 3-63 characters."

    # Only lowercase letters, digits, and hyphens allowed.
    allowed_characters = set("abcdefghijklmnopqrstuvwxyz0123456789-")
    if any(x not in allowed_characters for x in container_name):
        return "Only lowercase letters, numbers, and hyphens allowed."

    # Name must start and end with a letter or digit (no hyphen at edges).
    if not (container_name[0].isalnum() and container_name[-1].isalnum()):
        return "Start and end must be alphanumeric."

    # Two consecutive hyphens are not allowed.
    if "--" in container_name:
        return "No consecutive hyphens."

    # If we get here, the name is acceptable.
    return None

# Change the storage tier for a single blob.
def change_blob_tier(container_name: str, blob_name: str, new_tier: str) -> None:
    blob_client = blob_service_client.get_blob_client(
        container=container_name,
        blob=blob_name,
    )
    blob_client.set_standard_blob_tier(new_tier)

# Enrich a blob object from Azure with extra attributes:
def annotate_blob_with_costs(container_name, blob_obj) -> None:

    """
    Annotated with the following:

    - Mock usage data for different time windows (30/180/365 days).
    - Pricing estimates based on size, tier, and usage.
    - A suggested "optimal" tier, plus estimated savings.
    - Metadata fields that the UI uses to explain the suggestion.

    The function modifies blob_obj in-place by setting attributes on it.
    """

    # Capacity cost estimate for this blob using its current tier. Only depends on size and tier
    cap = pricing.estimate_capacity_month(
        size_bytes=blob_obj.size,
        tier=blob_obj.blob_tier,
    )

    # 30-day window
    _last_30, total_30, _hist_30 = mock_usage.get_mock_access_window(
        container_name=container_name,
        blob_name=blob_obj.name,
        window_days=30,
    )

    # 180-day window
    _last_180, total_180, _hist_180 = mock_usage.get_mock_access_window(
        container_name=container_name,
        blob_name=blob_obj.name,
        window_days=180,
    )

    # 365-day window. Used as a baseline later
    _last_365, total_365, _hist_365 = mock_usage.get_mock_access_window(
        container_name=container_name,
        blob_name=blob_obj.name,
        window_days=365,
    )

    # Full history across whatever period mock_usage tracks internally.
    _last_all, total_all, _hist_all = mock_usage.get_mock_access_window(
        container_name=container_name,
        blob_name=blob_obj.name,
        window_days=mock_usage.MAX_HISTORY_DAYS,
    )

    # This is the read count used to decide the "best" tier.
    reads_for_cost = total_all

    # Read cost in the current per month
    read_cost_now = pricing.estimate_read_cost_month(
        reads_count=reads_for_cost,
        tier=blob_obj.blob_tier,
    )

    # Creation age
    creation_time = getattr(blob_obj, "creation_time", None)
    if creation_time is not None:
        now = datetime.now(timezone.utc)
        days_since_creation = max(0, (now - creation_time).days)
    else:
        days_since_creation = None

    # Pull "business" metadata from the mock usage helper.
    meta = mock_usage.get_mock_blob_metadata(
        container_name=container_name,
        blob_name=blob_obj.name,
    )
    meta["days_since_creation"] = days_since_creation

    # Ask the pricing module which tier it thinks is best.
    opt_tier, _opt_month_raw, _per_tier = pricing.find_optimal_tier(
        size_bytes=blob_obj.size,
        reads_count=reads_for_cost,
        **meta,
    )

    # Baseline "reads per month" calculation:
    if total_365 and total_365 > 0:
        base_reads_per_month = total_365 / 12.0
    else:
        base_reads_per_month = 1.0  # small non-zero default

    # future_factor is a multiplier that tries to guess whether usage will go up or down compared to the last year, based on metadata.
    future_factor = 1.0

    # If the blob is flagged as having planned activity in the next 6 months, assume reads might roughly double.
    if meta.get("planned_activities_6m"):
        future_factor *= 2.0

    # If it is expected humans to open it regularly (e.g. reports, dashboards), bump the factor as well.
    human_index = meta.get("human_trigger_index", 0) or 0
    if human_index >= 3:
        future_factor *= 1.5
    if human_index >= 4:
        # Slight extra bump for very interactive blobs.
        future_factor *= 1.2

    # If the content is highly relevant (e.g. important media), nudge up again.
    relevance_index = meta.get("media_relevance", 0) or 0
    if relevance_index >= 4:
        future_factor *= 1.2

    # Clamp it to avoid absurd values if metadata is extreme.
    future_factor = max(0.5, min(future_factor, 5.0))

    # Expected reads per month, rounded down to an integer.
    expected_reads_per_month = int(base_reads_per_month * future_factor)
    if expected_reads_per_month < 0:
        expected_reads_per_month = 0

    # Estimate future cost per month for the current tier,
    future_current_month = pricing.estimate_total_month(
        size_bytes=blob_obj.size,
        reads_count=expected_reads_per_month,
        tier=blob_obj.blob_tier,
    )

    # Estimate future cost per month for the optimal tier.
    future_opt_month = pricing.estimate_total_month(
        size_bytes=blob_obj.size,
        reads_count=expected_reads_per_month,
        tier=opt_tier,
    )

    # Estimated savings if moved from current tier to optimal tier.
    opt_saving_est = future_current_month - future_opt_month

    # Attach values on the blob object for later use in the templates

    # Per-window read counts for display columns.
    setattr(blob_obj, "access_30d", total_30)
    setattr(blob_obj, "access_180d", total_180)
    setattr(blob_obj, "access_365d", total_365)

    # "Now" capacity and read estimates (mostly for debugging / consistency).
    setattr(blob_obj, "est_capacity_month", cap)
    setattr(blob_obj, "est_read_month", read_cost_now)

    # Totals used on the main listing page (based on "future" expected use).
    setattr(blob_obj, "est_total_month", future_current_month)
    setattr(blob_obj, "opt_tier", opt_tier)
    setattr(blob_obj, "opt_total_month", future_opt_month)
    setattr(blob_obj, "opt_saving_month", opt_saving_est)

    # Metadata exposed to the UI for the explanation modals.
    setattr(blob_obj, "criticality_index", meta.get("criticality_index", 0))
    setattr(blob_obj, "media_relevance", meta.get("media_relevance", 0))
    setattr(blob_obj, "human_trigger_index", meta.get("human_trigger_index", 0))
    setattr(blob_obj, "planned_activities_6m", meta.get("planned_activities_6m", False))
    setattr(blob_obj, "has_historical_links", meta.get("has_historical_links", False))
    setattr(blob_obj, "days_since_creation_meta", days_since_creation)

# VIEWS

# Main homepage view
def homepage(request):

    # POST HANDLING: actions that modify Azure state.
    if request.method == "POST":

        # Single blob: apply suggested tier (from modal)
        if "apply_tier_single" in request.POST:
            container_name = request.POST.get("container_name", "").strip()
            blob_name = request.POST.get("blob_name", "")
            target_tier = request.POST.get("target_tier", "")

            # These parameters let us return to the same listing page afterwards.
            prefix = request.POST.get("prefix", "").strip()
            page_size = request.POST.get("page_size", "").strip()
            page_num = request.POST.get("page_num", "").strip()

            # First check the container name is valid.
            error = check_container_name(container_name)
            if error:
                messages.error(request, error)
            elif not blob_name or not target_tier:
                messages.error(request, "Missing blob name or target tier.")
            else:
                # Try to call Azure and change the tier.
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

            # Redirect back to the same listing using the PRG pattern to avoid duplicate submissions.
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

        # Bulk apply tier changes
        if "apply_tier_bulk" in request.POST:
            container_name = request.POST.get("container_name", "").strip()

            # Again, reading listing params to rebuild the view after.
            prefix = request.POST.get("prefix", "").strip()
            page_size = request.POST.get("page_size", "").strip()
            page_num = request.POST.get("page_num", "").strip()

            error = check_container_name(container_name)
            if error:
                messages.error(request, error)
            else:
                # "items" is a list of strings formatted as "blob_name|target_tier".
                selected_items = request.POST.getlist("items")
                changed = 0

                for item in selected_items:
                    try:
                        blob_name, target_tier = item.split("|", 1)
                    except ValueError:
                        # If the format is wrong, just skip this one.
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

            # Redirect back to same listing (again using PRG pattern).
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

        # Create container (Currently commented out of homepage)
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

        # Upload blob to a container (Currently commented out)
        if "upload_blob" in request.POST:
            # Expect a file field named "blob_file" in the form.
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

            # Upload the file to Azure. Overwrite enabled
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

    # GET HANDLING: listing, charts, and non-mutating views.
    if request.method == "GET":
        # Common query parameters coming from the URL.
        container_name = request.GET.get("container_name", "").strip()
        prefix = request.GET.get("prefix") or None

        # Flags for whether should compute the global/container charts.
        show_global_chart = request.GET.get("show_global_chart") == "1"
        show_container_chart = request.GET.get("show_container_chart") == "1"

        # Page size (rows per page). Clamp to avoid silly values.
        try:
            page_size = int(request.GET.get("page_size", 100))
        except ValueError:
            page_size = 100
        page_size = max(10, min(5000, page_size))

        # Page number (1-based index).
        try:
            p = int(request.GET.get("p", "1") or "1")
        except ValueError:
            p = 1
        if p < 1:
            p = 1

        # These will be filled only if asked to show charts.
        global_current_total = None
        global_opt_total = None
        container_current_total = None
        container_opt_total = None

        # GLOBAL TOTALS: all containers, all blobs
        # Only computed if show_global_chart is true.
        if show_global_chart:
            total_cur = 0.0
            total_opt = 0.0

            # Loop over every container and every blob in the account.
            for c in blob_service_client.list_containers():
                c_name = c.name
                c_client = blob_service_client.get_container_client(c_name)

                for b in c_client.list_blobs():
                    # Add cost annotations to each blob
                    annotate_blob_with_costs(c_name, b)
                    total_cur += getattr(b, "est_total_month", 0.0)
                    total_opt += getattr(b, "opt_total_month", 0.0)

            global_current_total = total_cur
            global_opt_total = total_opt

        # PER-CONTAINER LISTING (if a container name is provided)
        if container_name:
            error = check_container_name(container_name)
            if error:
                # If the container name is invalid, show an error and stop.
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

            # Build the container client to talk to Azure.
            container_client = blob_service_client.get_container_client(
                container=container_name
            )

            try:
                # Fetch container properties
                container = container_client.get_container_properties()

                # Stream of all blobs in this container.
                blob_iter = container_client.list_blobs()

                # If a prefix is given, filter blobs by name (case-insensitive).
                if prefix:
                    prefix_lower = prefix.lower()
                    blob_list_all = []
                    for b in blob_iter:
                        if b.name.lower().startswith(prefix_lower):
                            blob_list_all.append(b)
                else:
                    # No prefix: just convert the iterator to a list.
                    blob_list_all = list(blob_iter)

                # Annotate each blob once (costs, suggestions, metadata).
                for b in blob_list_all:
                    annotate_blob_with_costs(container_name, b)

                # If the container chart is requested, compute totals across all blobs in this container.
                if show_container_chart:
                    container_current_total = sum(
                        getattr(b, "est_total_month", 0.0) for b in blob_list_all
                    )
                    container_opt_total = sum(
                        getattr(b, "opt_total_month", 0.0) for b in blob_list_all
                    )

                # Use Django's Paginator to split the blob list across pages.
                paginator = Paginator(blob_list_all, page_size)

                try:
                    page_obj = paginator.page(p)
                except PageNotAnInteger:
                    # If the page is not an integer, show the first one.
                    page_obj = paginator.page(1)
                    p = 1
                except EmptyPage:
                    # If it's out of range, show the last page instead.
                    page_obj = paginator.page(paginator.num_pages)
                    p = paginator.num_pages

                # Collect suggested tier changes, but only for the current page.
                suggestions = []
                for b in page_obj.object_list:
                    if getattr(b, "opt_tier", None) and b.opt_tier != b.blob_tier:
                        suggestions.append(b)

                # Build base query parameters for Prev/Next links.
                base_params = {
                    "container_name": container_name,
                    "page_size": page_size,
                }
                if prefix:
                    base_params["prefix"] = prefix

                # Previous page URL if available.
                prev_url = None
                if page_obj.has_previous():
                    params_prev = base_params.copy()
                    params_prev["p"] = page_obj.previous_page_number()
                    prev_url = f"{reverse('homepage')}?{urlencode(params_prev)}"

                # Next page URL if available.
                next_url = None
                if page_obj.has_next():
                    params_next = base_params.copy()
                    params_next["p"] = page_obj.next_page_number()
                    next_url = f"{reverse('homepage')}?{urlencode(params_next)}"

                # Everything the homepage template needs to render the listing.
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

                    # suggested changes (for the bulk modal)
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

            # Azure exceptions: translate into user-friendly messages.
            except ResourceNotFoundError:
                messages.error(request, "Container not found.")
            except ClientAuthenticationError:
                messages.error(request, "Not authorized. Check Azure login.")
            except HttpResponseError:
                messages.error(request, "Unexpected Azure error during listing.")

        # If reached here, either no container_name was given or something failed, just render the base homepage with whatever chart info we have.
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

    # Fallback: if the method is something else (HEAD, etc.), just show the homepage.
    return render(request, "homepage.html")

# Detailed view for a single blob
def blob_info(request, container, blob):

    # Build clients for both the blob and its container.
    blob_client = blob_service_client.get_blob_client(container=container, blob=blob)
    container_client = blob_service_client.get_container_client(container)

    # Properties for the specific blob and its container.
    props = blob_client.get_blob_properties()
    container_props = container_client.get_container_properties()

    # Tier: prefer blob_tier, fall back to access_tier if needed.
    # If neither exists, assume Hot as a conservative default.
    tier_raw = getattr(props, "blob_tier", None) or getattr(props, "access_tier", None) or "Hot"
    tier_norm = pricing._tier(tier_raw)

    # Size and unit price for this blob's tier.
    size_bytes = int(getattr(props, "size", 0))
    size_gb = size_bytes / pricing.BYTES_PER_GB
    unit_price = pricing.PRICE_PER_GB_MONTH[tier_norm]

    # Capacity-only estimate for the current tier.
    est_capacity = pricing.estimate_capacity_month(size_bytes=size_bytes, tier=tier_norm)

    # Mock read counts in different windows for more detail on usage.
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

    # Full history read count for the tier decision.
    _last_all, total_all, _hist_all = mock_usage.get_mock_access_window(
        container_name=container,
        blob_name=blob,
        window_days=mock_usage.MAX_HISTORY_DAYS,
    )
    reads_for_cost = total_all

    # Read cost estimate for the current tier based on full-history count.
    est_read_month = pricing.estimate_read_cost_month(
        reads_count=reads_for_cost,
        tier=tier_norm,
    )

    # Total current cost per month for this blob (capacity + reads).
    est_total = est_capacity + est_read_month

    # Age of the blob (days since creation). Some storage logic uses this to nudge old content to colder tiers.
    creation_time = getattr(props, "creation_time", None)
    if creation_time is not None:
        now = datetime.now(timezone.utc)
        days_since_creation = max(0, (now - creation_time).days)
    else:
        days_since_creation = None

    # Metadata describing how important this blob is, how likely humans are to open it, whether it is historical, etc.
    meta = mock_usage.get_mock_blob_metadata(
        container_name=container,
        blob_name=blob,
    )
    meta["days_since_creation"] = days_since_creation

    # Ask the pricing logic which tier it thinks is best and what that would roughly cost per month.
    opt_tier, opt_total, opt_per_tier = pricing.find_optimal_tier(
        size_bytes=size_bytes,
        reads_count=reads_for_cost,
        **meta,
    )
    opt_saving = est_total - opt_total

    # Pack everything into a context dict for the template.
    context = {
        # original objects (rarely used directly, but kept for completeness)
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

        # optimal tier suggestion and savings
        "opt_tier": opt_tier,
        "opt_total_month": opt_total,
        "opt_saving_month": opt_saving,

        # mock read counts for display
        "access_30d": total_30,
        "access_180d": total_180,
        "access_365d": total_365,
    }

    return render(request, "blob_info.html", context)
