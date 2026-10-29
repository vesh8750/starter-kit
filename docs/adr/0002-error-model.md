# 0002 — RFC 9457 problem details as the error contract

**Status:** Accepted

## Context

Error shape is a public API contract, and it leaks everywhere if left to individual
routes. The usual options are a bespoke envelope (`{"success": false, "error": {...}}`),
FastAPI's default `{"detail": ...}`, or the IETF standard.

FastAPI's default is inconsistent — a string for `HTTPException`, a list of objects for
validation errors — so clients end up special-casing it.

## Decision

A single `AppError` hierarchy in `core/errors.py`. Business code raises them; four
handlers in `core/exception_handlers.py` are the only place an exception becomes a
response. All errors serialise as `application/problem+json` per RFC 9457, with two
additions: a stable `code` for clients to branch on, and the `request_id`.

```json
{
  "type": "https://errors.example.com/pet_already_adopted",
  "title": "Conflict",
  "status": 409,
  "detail": "This pet is no longer available for adoption.",
  "code": "pet_already_adopted",
  "instance": "/api/v1/pets/018f.../reservation",
  "request_id": "5d1a...",
  "current_status": "reserved"
}
```

## Consequences

**Good.** One shape for every failure, including unhandled exceptions and 404s on
unknown routes. Clients branch on `code`, never on prose. Extension members carry
structured context (field violations, the conflicting constraint) without a new schema
per error. Every error is traceable to a log line via `request_id`. Server faults are
logged with a traceback and reported without internals.

**Costs.** Slightly more ceremony than `raise HTTPException(404)` — a new failure mode
usually means a small subclass. `HTTPException` raised by third-party code is caught and
re-rendered, so its shape is normalised but its `code` is generic.

## Rejected

A universal success envelope. It duplicates what the status code already says, makes
every client unwrap one level, and degrades generated clients and the OpenAPI schema.
List endpoints do use `{items, meta}` — the only case where the metadata has nowhere
else to live.
