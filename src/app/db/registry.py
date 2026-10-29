"""Model registry.

Alembic autogenerate only sees models that have been imported. Listing them by hand is
the obvious approach and the wrong one: forgetting a line does not raise -- it produces
an *empty* migration, and ``alembic check`` then agrees that nothing changed, because it
compares the database against metadata that is also missing the table. CI stays green
and the table simply never exists in production.

So the modules are discovered instead. Every ``app.modules.<feature>.models`` is
imported on startup; adding a feature requires no bookkeeping here, and the failure mode
that survived review disappears.
"""

from __future__ import annotations

import importlib
import pkgutil

import app.modules
from app.db.base import Base


def import_all_models() -> list[str]:
    """Import every feature's ``models`` module. Returns what was imported, for logging."""
    imported: list[str] = []
    for module_info in pkgutil.iter_modules(app.modules.__path__):
        if not module_info.ispkg:
            continue
        name = f"{app.modules.__name__}.{module_info.name}.models"
        try:
            importlib.import_module(name)
        except ModuleNotFoundError as exc:
            # A feature module without persistence is legitimate; a broken import
            # inside an existing models module is not, and must not be swallowed.
            if exc.name != name:
                raise
            continue
        imported.append(name)
    return imported


import_all_models()

__all__ = ["Base", "import_all_models"]
