"""Feature modules.

Each subpackage is a self-contained vertical slice of the product:

    modules/<feature>/
        models.py      SQLAlchemy models (the database shape)
        schemas.py     Pydantic request/response models (the API contract)
        repository.py  Query construction and persistence
        service.py     Business rules, orchestration, authorisation decisions
        router.py      HTTP surface: routing, status codes, dependency wiring
        exceptions.py  Feature-specific AppError subclasses

Modules own their data. Cross-module access goes through the other module's *service*,
never by importing its repository or querying its tables directly -- that boundary is
what keeps the slices independently understandable and refactorable.

See ``app/modules/pets`` for the reference implementation and docs/adding-a-feature.md.
"""
