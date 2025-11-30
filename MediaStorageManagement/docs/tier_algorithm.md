# Blob Tier Selection Algorithm — Detailed Documentation

The tier optimisation algorithm is the most important and most sophisticated component of the project. Its purpose is to select the most appropriate Azure Blob Storage tier for each media file based on:

- Price
- Usage
- Contextual metadata
- Predicted future behaviour
- Business rules
- Operational guardrails

It is implemented in:

utils/pricing.py - find_optimal_tier()

# 1. Problem Definition

Organisations struggle to manage:

- Expensive Hot storage
- Slow retrieval from Archive
- Lack of usage insight
- Millions of blobs with inconsistent behaviour

This algorithm aims to automate the decision while respecting:

- Cost efficiency
- Retrieval performance
- Business importance
- Metadata linkages
- Predictability

# 2. Algorithm Overview Diagram

flowchart:

A: [Input Metadata + Usage]
B: [Compute Raw Costs]
C: [Normalise Metadata]
D: [Compute Heat Score]
E: [Pick Ideal Tier Based on Heat]
F: [Apply Hard Guardrails]
G: [Compute Penalty-Adjusted Score]
H: [Choose Tier With Lowest Score]
I: [Return Tier + Raw Cost + Cost Table]

# 3. Inputs

# Blob Properties
- size_bytes
- reads_count

# Metadata
- criticality_index (0–5)
- media_relevance (0–5)
- human_trigger_index (0–5)
- planned_activities_6m (bool)
- has_historical_links (bool)
- days_since_last_access
- days_since_creation

These can later be sourced from:

- Telemetry logs
- Business systems
- Workflow contexts

# 4. Step-by-Step Logic

# Step 1 — Compute Raw Costs
For each of the four tiers:

raw_cost[tier] = capacity_cost + read_cost

This gives the unadjusted financial minimum.

# Step 2 — Normalise Metadata

Convert indices into 0–1 range.

criticality = crit_index / 5
relevance = media_rel / 5
human = human_index / 5
planned = bool → 0 or 1
age = min(days, 730) / 730

Age normalisation ensures old files tend to drift toward colder tiers.

# Step 3 — Compute the Heat Score

The heat score approximates how likely the blob is to be needed soon.

Interpretation:

- Higher heat: hotter tiers
- Lower heat: colder tiers

# Step 4 — Choose the Ideal (Target) Tier

Based solely on heat:

if heat >= 0.75 → Hot
elif heat >= 0.50 → Cool
elif heat >= 0.25 → Cold
else → Archive

This tier acts as an anchor — penalties are applied for deviating from it.

# Step 5 — Apply Hard Guardrails

These prevent nonsensical results (e.g., critical files in Archive).

Guardrails filter out unsafe tiers before scoring.

# Step 6 — Compute Penalty-Adjusted Score

Each allowed tier gets:

adjusted_cost = raw_cost + penalties

# Penalties include:

# 1. Distance Penalty
Discourages deviating from heat-implied ideal tier.

# 2. Archive Penalties
Restrict archive usage except when it makes sense.

# 3. Historical Discount
Historical materials that are low-criticality.

# 4. Size Penalties
Large blobs (>100 GB) are discouraged from staying hot.

# 5. Age Penalties
Old blobs (>1 year) drift toward cold tiers.

# Step 7 - Tier Selection

After raw cost + penalties:

best_tier = tier with lowest adjusted cost

The function returns:

# Why This Algorithm Outperforms Simpler Rules

Naive assumptions fail:

'Rarely accessed: Cold or Archive'

Azure pricing reality:

- Cold/Archive read costs are massive
- For small blobs (< few MB), Cold/Archive are more expensive
- Critical business files cannot tolerate Archive rehydration delays
- Human-trigger signals predict future reads
- Metadata from other systems must be respected

This algorithm:

- Handles Azure pricing accurately
- Enforces safety constraints
- Predicts future usage
- Provides deterministic and explainable results
- Optimises cost without sacrificing usability

# Future Extensions

- Replace mock usage with Log Analytics queries from a third party software
- Integrate with inspection systems (defects, assets, workflows)
- Feed into Power BI
- Create automated scheduled enforcement (Azure Functions)
- Feed machine learning models for prediction
