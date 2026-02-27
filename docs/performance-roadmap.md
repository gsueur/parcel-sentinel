# Performance Roadmap

**Status:** Draft
**Date:** 2026-02-28
**Scope:** Pipeline latency and concurrent regeneration throughput. Infrastructure, billing, and feature work are excluded.

---

## Current baseline

- Cold-start time (5-year window, residential connection): ~5 minutes
- Bottleneck: S3 I/O for COG reads (840 range requests at 8 concurrent)
- Concurrent regenerations: serialise on DuckDB write lock

**Already applied (v1.10.0):**
- `MAX_CONCURRENT_COG_READS`: 8 → 32
- `MAX_SCENES_PER_MONTH`: 2 → 1 (60 total scenes vs 120)
- Expected gain: 40-50% faster on same connection; larger gain on server with good S3 throughput

---

## Item 1 -- Deploy in AWS us-west-2

**Impact:** High. Expected 5-10× reduction in S2 COG read latency.
**Effort:** Infrastructure only, no code changes.

The `sentinel-cogs` S3 bucket (Sentinel-2 COGs) is in `us-west-2`. A range request from the same AWS region takes ~10-30 ms vs ~500-1500 ms over the open internet. With 60 scenes × 7 bands = 420 reads, colocation turns ~60-90 seconds of S3 I/O into ~5-10 seconds.

The SAR bucket (`sentinel-s1-l1c`) is in `eu-central-1`. Cross-region latency for SAR reads is unavoidable from us-west-2. Acceptable because SAR has 60 reads (vs 420 for S2) and is on a separate concurrent path.

**Deployment options (in order of simplicity):**
- Cloudflare Workers + R2 (no cold-start, global edge) -- not a fit here due to long compute times
- AWS Lambda (60s limit) -- too tight for cold starts
- AWS ECS Fargate in us-west-2 -- recommended: auto-scaling, no server management
- AWS EC2 t3.medium in us-west-2 -- simplest, adequate for current load

**Environment variables to set:**
```
ENV=production
AWS_DEFAULT_REGION=us-west-2
```

No code changes required. `AWS_NO_SIGN_REQUEST=YES` is already set in the SAR pipeline for anonymous S3 access.

---

## Item 2 -- Async job queue

**Impact:** High UX improvement. Eliminates HTTP timeout risk. Enables concurrent regeneration without client-side polling hacks.
**Effort:** ~1-2 days.

Currently `POST /v1/locations` and `POST /v1/location/{key}/regenerate` block until the full pipeline completes. At 5 minutes per location, 4 concurrent regenerations require either a 20-minute timeout or the client to give up.

### Proposed flow

```
POST /v1/location/{key}/regenerate
→ 202 Accepted
  { "job_id": "job_abc123", "status_url": "/v1/jobs/job_abc123" }

GET /v1/jobs/job_abc123
→ { "status": "running", "started_at": "...", "location_key": "..." }
  or
→ { "status": "done", "location_key": "...", "result": { ... full response ... } }
  or
→ { "status": "failed", "error": "..." }
```

Frontend polls `/v1/jobs/{id}` every 5 seconds and updates the card when done.

### Recommended stack

**ARQ** (async Redis Queue) -- minimal, asyncio-native, no Celery overhead:

```
pip install arq
```

- One `arq` worker process alongside uvicorn
- Jobs stored in Redis (also used for response caching if added)
- Job results persisted for 24 hours in Redis, then discarded (DuckDB has the durable result)
- Redis also acts as the in-memory cache layer (replacing the current in-process dict cache, which doesn't survive restarts or share across workers)

**Infrastructure addition:** Redis instance (AWS ElastiCache t3.micro ~$15/month, or a free-tier Redis Cloud instance for dev).

### Key design decisions

- `POST /v1/locations` (new location) can remain synchronous for now -- it's a one-time event and the response is needed to get the `location_key`
- `POST /v1/location/{key}/regenerate` is the primary target -- this is the batch operation
- The frontend already has the `location_key` before regeneration, so 202 + poll is natural

---

## Item 3 -- PostgreSQL for concurrent write workloads

**Impact:** Eliminates DuckDB write serialisation when regenerating multiple locations concurrently.
**Effort:** ~2-3 days (schema migration + store rewrite).

### Problem

DuckDB grants an exclusive file lock to one writer at a time. With multiple concurrent regenerations (or multiple uvicorn workers):
- Single worker: writes serialise through the one connection, blocking the event loop
- Multiple workers: second worker gets `database is locked` immediately

### Proposed split

Keep DuckDB for write-once, read-heavy caches. Move result tables to PostgreSQL.

| Table | Store | Rationale |
|-------|-------|-----------|
| `location_geometries` | PostgreSQL | Written on every new location |
| `location_features` | PostgreSQL | Written on every regeneration |
| `location_scores` | PostgreSQL | Written on every regeneration |
| `location_timeseries` | PostgreSQL | Written on every regeneration |
| `customers` | PostgreSQL | Config data |
| `band_arrays` | DuckDB | Written once per scene, never changes, large FLOAT[4096] blobs |
| `sar_band_arrays` | DuckDB | Same |
| `terraclimate_monthly` | DuckDB | Written once per grid cell, shared across locations |

### Implementation notes

- Use `asyncpg` for async PostgreSQL access (no SQLAlchemy needed for this schema complexity)
- Connection pool: 10-20 connections via `asyncpg.create_pool()`
- `duckdb_store.py` splits into `pg_store.py` (result tables) + `duckdb_store.py` (cache tables only)
- Migration: one-time export from DuckDB → import into Postgres (small data volume, manageable manually)
- `POSTGRES_DSN` config key already exists as a placeholder

### Schema notes

PostgreSQL handles the `FLOAT[4096]` band array columns differently -- use `BYTEA` or keep those in DuckDB (preferred). The `series_json` timeseries columns map cleanly to `JSONB`.

**Recommended hosting:** AWS RDS PostgreSQL t3.micro (~$15/month) in the same VPC as the application server.

---

## Item 4 -- SAR executor pool tuning

**Impact:** Low-moderate. Removes potential thread starvation for concurrent SAR reads.
**Effort:** 1 hour.

SAR reads use `rasterio WarpedVRT` synchronously in `asyncio.run_in_executor`. The default asyncio executor has `min(32, cpu_count + 4)` threads. On a 2-core instance that's 6 threads -- fine for one pipeline, potentially a bottleneck for 4 concurrent ones.

```python
# In app.py create_app():
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=32, thread_name_prefix="sar-read")
loop = asyncio.get_event_loop()
loop.set_default_executor(executor)
```

This should be done alongside the async job queue (Item 2) since the combination of both is what creates the high-thread-count scenario.

---

## Summary and sequencing

| # | Item | Effort | Unblocks |
|---|------|--------|---------|
| ✅ | `MAX_CONCURRENT_COG_READS=32`, 1 scene/month | Done | Immediate gain |
| 1 | Deploy in us-west-2 | Infrastructure | 5-10× S2 read speed |
| 2 | Async job queue (ARQ + Redis) | ~2 days | Concurrent regenerations, timeout safety |
| 3 | PostgreSQL for result tables | ~3 days | True concurrent writes; depends on 2 for full value |
| 4 | SAR executor pool tuning | 1 hour | Do alongside 2 |

Items 1 and 2 are independent and can be done in parallel. Item 3 becomes relevant once Item 2 enables genuinely concurrent regenerations at scale.
