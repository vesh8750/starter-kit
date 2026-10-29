"""Reusable column types.

:func:`enum_column` exists because of a genuine SQLAlchemy footgun: ``Enum(SomeEnum)``
persists the member *names* (``DOG``) rather than the values (``dog``). That silently
diverges from what the API serialises, and it only fails once a ``server_default`` or a
hand-written SQL query uses the value. Always build enum columns through this helper.
"""

from __future__ import annotations

import enum

from sqlalchemy import Enum


def enum_column[E: enum.Enum](enum_cls: type[E], name: str) -> Enum:
    """Native Postgres enum that stores member *values*.

    ``validate_strings`` makes SQLAlchemy reject a raw string that is not a member,
    rather than passing it through to the database.
    """
    return Enum(
        enum_cls,
        name=name,
        native_enum=True,
        validate_strings=True,
        values_callable=lambda members: [str(member.value) for member in members],
    )
