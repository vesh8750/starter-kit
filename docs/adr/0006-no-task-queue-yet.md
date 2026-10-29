# 0006 — No task queue in the foundation

**Status:** Accepted

## Context

Most production backends eventually need background work: emails, webhooks, report
generation, scheduled jobs. Celery is the reflexive choice. Redis is already available
here for caching, so arq or Dramatiq would also be cheap to add.

## Decision

No task queue in the initial foundation. `BackgroundTasks` covers fire-and-forget work
that may safely be lost, and the extension point is documented instead.

## Rationale

A queue is not one dependency, it is an operating model: a second process to deploy,
scale, monitor and page on; a serialisation contract between producer and consumer;
retry, idempotency and dead-letter semantics; and its own failure modes. Adopting all of
that before a single job exists means guessing at requirements — and a wrong guess is
harder to remove than a missing one is to add.

The parts that make adding a queue awkward are already solved: `session_scope()` gives
non-request code a proper transaction, settings and structured logging work identically
outside a request, and services are callable without HTTP.

## When to revisit

Add a queue as soon as any of these is true — and pick arq, which fits the existing
Redis and the async codebase, unless something specific argues otherwise:

* work must survive a process restart,
* work must be retried with backoff,
* work must run on a schedule,
* work takes long enough that a request should not wait for it.

Until then, `BackgroundTasks` is honest about what it does: best-effort work that runs
after the response and is lost if the process dies.
