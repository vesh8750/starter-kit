# 0001 — Vertical feature slices over a shared core

**Status:** Accepted

## Context

The two common layouts for a FastAPI application are layer-first (`routers/`,
`services/`, `models/`, `schemas/`) and feature-first (`modules/<feature>/…`). The choice
is hard to reverse once dozens of files exist, and it determines the answer to the
question developers ask most often: *where does this code go?*

## Decision

Feature slices under `src/app/modules/<feature>/`, each containing its own `router`,
`schemas`, `service`, `repository`, `models` and `exceptions`. Cross-cutting
infrastructure lives in `core/`, `db/`, `cache/`, `storage/`, `integrations/` and
`observability/`.

One hard rule: **a module may call another module's service, but never its repository or
its tables.**

## Consequences

**Good.** A feature's code is in one directory. Adding one is a copy-and-adapt, deleting
one is `rm -r` plus two registration lines. Merge conflicts between teams working on
different features become rare. The boundary is explicit enough that a slice could later
be extracted into its own service without archaeology.

**Costs.** Two registration steps are easy to forget: the model import in
`db/registry.py` (Alembic sees nothing otherwise) and the router include in
`api/v1/__init__.py`. Shared concepts need a deliberate home rather than drifting into
whichever module used them first.

## Rejected

*Layer-first* optimises for the rarest change (touching every model at once) and
penalises the common one. *Clean/Hexagonal* would require three parallel representations
of every entity and hand-written mappers — real cost for a benefit this domain does not
currently need. The one part worth keeping, dependency inversion at infrastructure
boundaries, is kept: storage, cache and HTTP clients are protocols.
