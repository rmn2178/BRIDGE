# Optimization Decision Matrix

| Optimization | Why | Impact | Tradeoff |
| --- | --- | --- | --- |
| Parallel FHIR fetch (asyncio.gather) | Eliminates sequential latency | P99 reduced under load | Slightly higher concurrency load |
| L1 RiskCard cache (TTL 5 min) | Most calls repeat per patient | P50 < 200ms for cached | Potential stale data |
| L2 Redis bundle cache (TTL 10 min) | Reduce external FHIR calls | 60%+ fewer external calls | Requires Redis in prod |
| Connection pooling | Reuse TCP/TLS | Higher throughput | Pool tuning needed |
| Request coalescing | Avoid thundering herd | Lower FHIR load | Small lock overhead |
| Gzip compression | Reduce payload size | Faster transfers | CPU overhead |
| Lazy loading | Skip bundle when not needed | Lower latency | Slight branching logic |
