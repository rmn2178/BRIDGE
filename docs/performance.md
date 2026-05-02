# Performance

BRIDGE uses pooled HTTP connections, request coalescing, and multi-level caching.

## Caching
- L1 in-memory cache for RiskCards
- L2 Redis cache for FHIR bundles

## Tooling
- `perf/locustfile.py` for load testing
- `perf/benchmark.py` for latency snapshots
- `perf/memory_profile.py` for memory sampling
