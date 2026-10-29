# 0007 — What the architecture review changed

**Status:** Accepted

## Context

Before feature work began, the foundation was reviewed against the running code rather
than the documentation. The test suite was green throughout, which is the point: every
defect below was invisible to it.

## Findings that changed the code

| # | Defect | Why the tests missed it |
|---|---|---|
| 1 | **Commit failures returned `200 OK`** with a success body while the transaction was rolled back | The test session override only committed on the happy path; no test exercised a failing commit |
| 2 | Production booted with a **randomly generated `SECRET_KEY`** and a **localhost `DATABASE_URL`** | Defaults are convenient and only wrong once deployed |
| 3 | Upload extension taken from the **client's filename** (`payload.html` + `image/png` → stored `.html`) | The test asserted the *prefix* was safe, not the extension source |
| 4 | Upload wrote the object **before checking the owning row existed** | No test uploaded to a missing id |
| 5 | The superseded file was **deleted before the commit** | Requires a commit failure after a successful upload |
| 6 | `UploadFile.file` read **synchronously on the event loop** | Correct output; only latency suffers, and only under load |
| 7 | `create_app(settings)` built an app whose **lifespan ignored those settings** | Tests never ran the lifespan |
| 8 | `InMemoryCache` returned **shared mutable references**; Redis returns copies | Backend-dependent, and the divergence favours the test backend |
| 9 | Offset pagination had **no unique tiebreaker** — pages could repeat and skip rows | Needs duplicate sort keys *and* an unlucky plan |
| 10 | Metric route labels were built by **string substitution**, corrupting labels when a value equalled a literal segment | Only wrong for specific values |
| 11 | `reserve()` was a **read-decide-write race** — two callers could both win | Requires true concurrency |
| 12 | Model registry was a **hand-maintained import list**; a missing line produces an empty migration *and* a passing `alembic check` | The failure is silence |
| 13 | Our `ValidationError` **shadowed Pydantic's** | Works until someone writes `except ValidationError` |
| 14 | **No request body size limit** — bodies were buffered before any code ran | Requires a hostile client |
| 15 | Authentication and authorisation had **no HTTP-level tests** and no protected route | Nothing exercised them |

## Decisions confirmed, not changed

Vertical slices, the `AppError`/RFC 9457 error model, one-request-one-transaction as a
*principle*, concrete per-feature repositories, storage behind a protocol, auth
primitives without an auth system, and the absence of a task queue all held up. Only
finding 1 changed a mechanism; the rest were implementation defects or gaps.

## Consequences

Three of these (1, 11, 12) share a shape worth naming: **the failure mode is silence.**
No error, no failing test, no log line — a wrong result or a missing table. Each now has
a regression test that asserts the *reason*, not just the behaviour, so the next person
to touch it learns why the constraint exists instead of deleting it.
