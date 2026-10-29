# 0003 — One request, one transaction

**Status:** Accepted

## Context

Transaction boundaries have to live somewhere. The candidates: each repository method
commits; the service commits; or the request owns the transaction.

Per-method commits are the most common accident. They make it impossible for a service
to combine two writes atomically — a failure halfway through leaves the database in a
state no code intended.

## Decision

The `DbSession` dependency opens a session, yields it, and **commits when the endpoint
returns normally, rolling back if anything raises.** Services and repositories never
call `commit()`; they call `flush()` when they need a generated value.

Code outside the request cycle uses `session_scope()`, which has the same semantics for
its own transaction.

## Consequences

**Good.** Every request is atomic by construction, with no ceremony at the call site. A
service can orchestrate several repositories and still produce one unit of work.
Rollback on error is automatic, so a partially-applied request is not a class of bug
that exists here. Driver errors are translated centrally (integrity violation → 409,
connection loss → 503).

**Costs.** Background tasks must not reuse the request session — it is closed by the
time they run — which is why `session_scope()` exists and is documented. Long-running
endpoints hold a connection for their duration; the 15s `statement_timeout` bounds the
damage. A genuinely long operation belongs in a background job, not a request.

**Also:** because the commit happens after the endpoint returns, `expire_on_commit=False`
is required or serialisation would trigger lazy loads on expired attributes — which
under asyncio raises `MissingGreenlet`.
