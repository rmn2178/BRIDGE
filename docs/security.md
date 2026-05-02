# Security

BRIDGE supports JWT and API key authentication. Configure settings via environment variables:

- `AUTH_REQUIRED`: require JWT when true
- `JWT_SECRET`: signing secret
- `JWT_ALGORITHM`: default `HS256`
- `JWT_ISSUER`, `JWT_AUDIENCE`: optional validation
- `API_KEYS`: comma-separated API keys
- `SHARP_FHIR_ALLOWLIST`: comma-separated FHIR hosts
- `RATE_LIMIT_PER_WINDOW`, `RATE_LIMIT_WINDOW_SECONDS`
- `AUDIT_LOG_ENABLED`
