# Running it in production

## Image

`make docker-build` produces a multi-stage image: dependencies resolved from the
lockfile in a builder stage, then only the virtualenv and application copied into a
clean runtime. No build tools, no `uv`, no tests, non-root user.

## Startup order

1. **Migrations run as a separate step** — a job or init container — before the new
   version starts. Never in the application's `CMD`: with more than one replica that
   races on every scale-up.
2. The application starts, `lifespan` creates the engine, cache and storage. A
   misconfiguration fails here, not on first traffic.
3. The orchestrator polls `/health/ready` before sending traffic.

## Probes

| Endpoint | Use for | Fails when |
|---|---|---|
| `/health/live` | Liveness — restart decisions | The process is broken. Never on a dependency fault |
| `/health/ready` | Readiness — load balancer membership | A dependency is down (503) |
| `/health` | Human inspection | — |

Pointing a liveness probe at the readiness endpoint is a classic outage amplifier: a
brief database blip then restarts every replica at once.

## Configuration

Inject environment variables from your platform's secret store. Required in production:

```
ENVIRONMENT=production
DEBUG=false
LOG_RENDERER=json
SECRET_KEY=<generated per environment>
DATABASE_URL=postgresql+asyncpg://...
CORS_ORIGINS=["https://app.example.com"]
TRUSTED_HOSTS=api.example.com
```

The application refuses to start if any of these are unsafe.

## Logs

JSON to stdout, one object per line, every request-scoped line carrying `request_id`.
Ship with whatever your platform uses; do not write log files.

Useful queries: `event="http.request" AND status_code>=500`,
`event="request.unhandled_exception"`, `request_id="..."` to reconstruct one request.

## Metrics

`/metrics` in Prometheus format: `http_requests_total` and
`http_request_duration_seconds`, labelled by method, route template and status. Alert on
error rate and p99 latency per route; scrape internally and do not expose it publicly.

## Scaling

* `--workers N` ≈ CPU cores. Each worker has its own connection pool, so
  `DATABASE_POOL_SIZE × workers × replicas` must stay under the database's
  `max_connections` — put PgBouncer in front before that becomes tight.
* `statement_timeout` (default 15s) stops a runaway query from holding a connection.
* `pool_pre_ping` lets the pool survive database restarts and idle-connection reaping.

## Rollback

Application rollbacks are safe as long as each migration is backwards-compatible with
the previous release — which is why expand/contract (add nullable, backfill, switch
reads, drop later) is the rule for schema changes, rather than one destructive step.
