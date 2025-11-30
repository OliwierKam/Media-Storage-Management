# Pricing Engine Documentation

The pricing engine (utils/pricing.py) computes storage pricing using real Azure numbers for:
Germany West Central, RA-GRS, HNS

# 1. Storage Capacity Cost

Price per GB per month:

Tier | £/GB·mo

Hot | 0.0371
Cool | 0.01889
Cold | 0.00763
Archive | 0.00211

Formula:

cost = (size_bytes / (1024**3)) * unit_price

# 2. Read Operation Cost

Read pricing per 10,000 operations:

Tier | £/10k reads

Hot | 0.0044
Cool | 0.0100
Cold | 0.1000
Archive | 5.50

read_cost = (reads / 10000) * price

# 3. Combined Monthly Cost

total = capacity_cost + read_cost

Used by:

- Blob cost annotation
- Algorithm’s raw cost table
- Cost charts
- Savings calculations

# 4. Tier Normalisation

Accepts variants:

- cool_zrs
- Hot LRS
- archive(rehydrate)
- COLD

Maps reliably to one of:

["Hot", "Cool", "Cold", "Archive"]

