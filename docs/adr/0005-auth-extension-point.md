# 0005 — Auth primitives without an auth system

**Status:** Accepted

## Context

Authentication is where a foundation most easily guesses wrong. Are users local or
federated? Is there a JWT, a session cookie, an opaque token, an API key? Roles or
scopes? Multi-tenant? Each answer produces a different user table and a different login
flow, and none of them can be derived from technical reasoning alone.

But the mechanical half — password hashing, token signing and verification, extracting a
caller from a request, enforcing permissions — is identical across all of them, and is
easy to get subtly wrong.

## Decision

Ship the mechanics, not the policy.

* `core/security.py`: Argon2id hashing (with a verify-and-upgrade path) and signed,
  expiring JWTs.
* `core/context.py`: a `Principal` (subject + scopes), deliberately decoupled from any
  user table.
* `api/deps.py`: `CurrentPrincipal` (401 when absent), `OptionalPrincipal`, and
  `require_scopes("...")` (403 when under-privileged).

There is no user model, no registration and no login endpoint.

## Consequences

**Good.** Endpoints can be protected today. Adding real auth means adding a `modules/users`
slice and one route that issues a token — the route protection, the principal plumbing
and the error shapes already exist and do not change. Because `Principal` carries only a
subject and scopes, the same dependencies work for user sessions, API keys or
machine-to-machine clients.

**Costs.** `create_access_token` is unused until something calls it, and unused code
invites bit-rot — it is covered by tests for that reason. Symmetric HS256 means every
verifier needs the signing secret; moving to RS256/EdDSA is a settings change plus a key
source, and is the right move as soon as a second service verifies these tokens.

**Not provided, on purpose:** refresh tokens and rotation, token revocation (JWTs are
valid until they expire — if immediate revocation is required, use short TTLs plus a
denylist in the cache, or opaque tokens), and password reset flows.
