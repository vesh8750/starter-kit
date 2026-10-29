# Architecture

## The shape

The application is organised as **vertical feature slices over a shared infrastructure
core**.

```
          ┌──────────────────────────────────────────┐
 HTTP ───▶│ middleware: request id, security, metrics│
          └───────────────────┬──────────────────────┘
                              ▼
                     api/v1 router
                              │
      ┌───────────────────────┴────────────────────────┐
      ▼                        ▼                        ▼
 modules/pets           modules/orders            modules/...
   router.py              router.py                (a slice per feature)
   service.py             service.py
   repository.py          repository.py
   models.py              models.py
      │                        │
      └───────────┬────────────┘
                  ▼
   core/ · db/ · cache/ · storage/ · integrations/ · observability/
```

The question "where does this code go?" has one answer: **feature code goes in its
slice; anything two features would both need goes in the core.**

### Why not layer-first (`routers/`, `services/`, `models/`)?

Layer-first directories optimise for the rarest operation (changing every model at once)
and penalise the common one (changing one feature). A change to "orders" then touches
five directories, and nothing tells you which files belong together. Slices keep a
feature's code in one place, make deletion trivial, and make ownership obvious.

### Why not Clean/Hexagonal architecture?

Ports-and-adapters pays off when the domain is large and genuinely independent of its
delivery mechanism. Here it would mean duplicating every model three times (ORM entity,
domain entity, DTO) and hand-writing mappers between them — real cost, for a benefit
this application does not currently need. What we *do* borrow is the part that carries
its weight: **the business layer depends on protocols, not on providers**
(`FileStorage`, `Cache`, `ServiceClient`), so infrastructure is swappable at the edges
where it actually changes.

If a genuinely complex domain emerges later, a module can grow a `domain.py` internally
without affecting any other slice. That is the point of the boundary.

## Layers inside a slice

| File | Responsibility | Must not |
|---|---|---|
| `router.py` | Routing, status codes, dependency wiring | Contain business rules or SQL |
| `schemas.py` | The API contract (validation, serialisation) | Be reused as the ORM model |
| `service.py` | Business rules, orchestration, authorisation | Touch `Request`/`Response`, or commit |
| `repository.py` | Query construction, persistence | Contain business rules, or commit |
| `models.py` | Database shape and integrity constraints | Contain presentation logic |
| `exceptions.py` | Feature-specific `AppError` subclasses | Build HTTP responses |

**Cross-module rule:** a module may call another module's *service*. It may never import
another module's repository or query its tables. That single rule is what keeps slices
independently refactorable.

## Cross-cutting decisions

### Errors — RFC 9457 problem details
Every failure is an `AppError`. Handlers in `core/exception_handlers.py` are the only
place an exception becomes a response. Clients branch on the stable `code` field; every
error carries the `request_id`. See [ADR 0002](adr/0002-error-model.md).

### Transactions — one request, one transaction
`DbSession` commits when the endpoint returns and rolls back if anything raises.
Services never call `commit()`, so a request is atomic by construction. Work that must
outlive or escape the request uses `session_scope()`.

The dependency is `scope="function"`, which is load-bearing: request-scoped `yield`
dependencies are torn down *after* the response is sent, so a commit failure could not
change the status code and the client received `200 OK` for a rolled-back transaction.
See [ADR 0003](adr/0003-transaction-boundary.md).

**Read-decide-write rules must lock the row** (`get_for_update`). "Only allowed if the
status is X" is a lost update without `SELECT ... FOR UPDATE`; `PetService.reserve` is
the reference.

### Responses — resources, not envelopes
Single resources are returned directly. List endpoints return `Page[T]`
(`{items, meta}`), because page metadata genuinely has nowhere else to live. Errors use
`application/problem+json`. A universal `{"success": true, "data": ...}` wrapper was
rejected: it duplicates HTTP semantics and makes generated clients worse.

### Logging and tracing
`structlog`, event names plus key/value fields, console locally and JSON when deployed.
Every line inside a request carries `request_id`, taken from an inbound `X-Request-ID`
when present and echoed on the response — so one id follows a call from the gateway
through the logs to the client's bug report. Outbound `ServiceClient` calls propagate it
onward.

### Configuration
One typed `Settings` object, read once, validated at import. Nothing reads `os.environ`.
Deployed environments are additionally validated (no debug, no wildcard CORS, no
placeholder secret) so a misconfiguration fails the deploy, not a customer request.

### Authentication — an extension point, not a system
`core/security.py` provides Argon2id hashing and signed JWTs; `api/deps.py` provides
`CurrentPrincipal` and `require_scopes(...)`. There is deliberately no user model or
login endpoint — those are product decisions. Adding "user registration" means adding a
`modules/users` slice and one route that issues a token; nothing structural changes.
See [ADR 0005](adr/0005-auth-extension-point.md).

### Files and images
Services deal in **storage keys** through the `FileStorage` protocol and never in paths,
buckets or URLs. Keys are fully generated and their extension comes from the *validated
content type*, never from the client's filename. Request bodies are capped by
`MaxBodySizeMiddleware` before anything is buffered; the per-endpoint `max_bytes` is a
second limit applied while writing. The local backend ships; S3 is a `factory.py` case and one adapter.
Image processing (resizing, format conversion, virus scanning) is intentionally absent
until a product requirement defines it — the protocol is what makes adding it a feature
rather than a refactor. See [ADR 0004](adr/0004-storage-abstraction.md).

### Caching
`Cache` protocol, in-memory by default, Redis by configuration. Cache failures are
logged and swallowed: a cache outage degrades latency, it does not take the API down.
Anything that must be correct lives in the database.

### Observability
`/health/live` (no dependencies — never restarts a pod over a database blip),
`/health/ready` (dependency checks — removes an instance from the load balancer), and
`/metrics` (RED metrics with bounded-cardinality route labels).

## Deliberate omissions

These are extension points, not oversights. Each has a clear "add it when" trigger.

| Not included | Add it when | How |
|---|---|---|
| Task queue (Celery/arq/Dramatiq) | Work must survive a restart, be retried, or run on a schedule | `FastAPI BackgroundTasks` covers fire-and-forget now; arq fits the existing Redis. Use `session_scope()` for its database access |
| Distributed tracing (OpenTelemetry) | This service calls two or more others | The request id already propagates, which is the hard part |
| Rate limiting | The API is publicly exposed | Usually belongs at the gateway; otherwise a middleware over the `Cache` protocol |
| Cursor pagination | A collection is large or high-churn enough that `OFFSET` hurts | Add `after`/`before` params next to the existing offset support. Ordering is already a total order, which is the precondition |
| Orphaned-file sweeper | Uploads are replaced often enough that superseded objects matter | A periodic job reconciling storage keys against referencing rows. Superseded keys are logged as `pet.photo_superseded` today |
| Read replicas, sharding, CQRS, event sourcing | Measured need | Not before |
| Multi-tenancy | The product requires it | Decide row-level vs schema-level first; retrofitting is expensive |

## Request lifecycle

1. `RequestContextMiddleware` assigns/propagates the request id and binds log context.
2. `SecurityHeadersMiddleware` prepares response headers.
3. `MetricsMiddleware` starts the latency timer.
4. CORS, trusted hosts, gzip.
5. FastAPI resolves dependencies: settings, `DbSession` (opens a transaction),
   pagination, principal.
6. The route calls a service; the service applies rules via repositories.
7. On return, the session **commits**; on an exception it **rolls back** and the
   handlers render a problem document.
8. Middleware records metrics and emits one access log line with the duration.
