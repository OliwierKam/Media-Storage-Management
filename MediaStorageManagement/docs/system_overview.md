# System Overview

The Media Storage Management project automates intelligent storage tiering for media in Azure Blob Storage. It acts as a decision-support tool, helping organisations minimise storage cost while ensuring important files remain quickly accessible.

# Business Context

Modern inspection and document-heavy systems accumulate thousands of media items.
Common issues:

- Old media is kept in expensive Hot storage
- Critical files end up in Cold by accident
- Retrieval delays cause workflow problems
- Human review is inconsistent and costly

This project automates rational storage placement based on:

- Usage history
- Business relevance
- Predicted future access
- Azure pricing models

It is also possible to rationalise content relationships with the addition of a seperate software that will store relational data information.

# Key Capabilities

- List containers and browse by prefix
- View per-blob statistics and cost
- Estimate current vs optimal monthly bills
- Suggest tier migration
- Allow bulk or single blob updates
- Visualise costs with charts
- Simulate access data where unavailable

# Algorithm-Centric Design

The entire system is oriented around the tier optimisation algorithm, which:

- Learns from metadata
- Enforces guardrails
- Balances cost vs performance
- Predicts future usage
- Produces per-tier cost models

It is configurable, explainable, and behaves consistently.
