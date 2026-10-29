# 0004 — Storage behind a protocol; the business layer holds keys

**Status:** Accepted

## Context

The application will need image and file handling. The tempting shortcut is to write
files where they are needed and store a path or a URL on the model. That choice is
discovered to be wrong at the worst moment — when moving to object storage, adding a CDN,
or running more than one instance — and by then the paths are in the database.

## Decision

A `FileStorage` protocol (`save`, `open`, `delete`, `exists`, `url_for`). Services
depend on the protocol and persist only an opaque **storage key**
(`pets/2026/01/ab12….jpg`). URLs are produced at serialisation time via
`storage.url_for(key)`.

`LocalFileStorage` ships. S3 is a case in `storage/factory.py` plus one adapter.

Deliberately **not** built: resizing, format conversion, thumbnails, virus scanning, CDN
signing, async processing pipelines.

## Consequences

**Good.** Switching backends changes one factory line and rewrites no rows. Uploads are
streamed with a size limit enforced mid-flight, so a large file is rejected before it is
buffered. Writes are atomic (temp file + rename), so a crash cannot leave a half-written
object under a live key. Keys are generated, date-partitioned and path-traversal-safe —
a filename like `../../etc/passwd` cannot influence where anything lands. Tests point the
same code at a temp directory.

**Costs.** Unreferenced objects accumulate until a sweeper exists (see above). The local
backend does not support signed URLs, so `url_for` ignores
`expires_in`; a service that needs expiry must not assume it. Serving files from local
disk needs a static route or a reverse proxy, which is fine for development and
single-node deployments and is one reason to move to S3 sooner.

## Amendment (architecture review)

Three defects were found in the first implementation and fixed:

1. **The stored extension came from the client's filename.** A client could upload
   `payload.html` while declaring `image/png` and get a `.html` object written to a
   location intended to be served over HTTP — stored XSS. Extensions are now derived
   solely from the *validated* content type; unrecognised types become `.bin`.
2. **The object was written before the owning row was checked**, so every upload to a
   missing id left an orphaned file. The row is now loaded first.
3. **The superseded object was deleted before the transaction committed.** A failure
   after that point left a live row pointing at a deleted file. Superseded keys are now
   logged for a sweeper instead; an unreferenced object is cheap, a missing referenced
   one is unrecoverable.

Also corrected: the claim that `max_bytes` rejects a large upload "mid-flight". It does
not — the framework buffers the body before the endpoint runs. `MaxBodySizeMiddleware`
is the real first line of defence; `max_bytes` is the second, per-endpoint limit.

## When to extend

Image processing arrives with a product requirement. The natural shape is a
`modules/media` slice that owns variants (original, thumbnail, web) as separate keys and
does the work in a background job — not inline in the request. The protocol is what
makes that an addition rather than a refactor.
