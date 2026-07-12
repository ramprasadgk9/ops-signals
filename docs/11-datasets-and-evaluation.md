# Datasets and Evaluation

## Current Inputs

- canonical CSV samples in `sample_data/`

## What Should Be Evaluated

- ingestion correctness
- normalization consistency
- signal generation behavior
- finding aggregation quality
- case lifecycle persistence
- memory retrieval usefulness

## Evaluation Guidance

- Prefer representative samples over synthetic claims
- Compare analyzer output against known input patterns
- Treat similarity retrieval as a ranking aid, not ground truth

## Current State

The repository includes sample datasets and tests, but no public benchmark claims.
