from __future__ import annotations

import pytest

from app.core.errors import InputValidationError
from app.core.pagination import Page, PageParams, SortParams


def test_page_metadata_reports_more_pages():
    page = Page[int].build([1, 2], total=10, params=PageParams(limit=2, offset=0))
    assert page.meta.has_more is True
    assert page.meta.total == 10


def test_page_metadata_on_last_page():
    page = Page[int].build([9, 10], total=10, params=PageParams(limit=2, offset=8))
    assert page.meta.has_more is False


def test_sort_parsing_handles_direction_prefixes():
    sort = SortParams.parse("-created_at,name", allowed=("created_at", "name"), default="name")
    assert sort.fields == (("created_at", True), ("name", False))


def test_sort_always_appends_a_unique_tiebreaker():
    """Offset pagination over a non-unique key is unstable without a total order."""
    from sqlalchemy import Column, Integer, String, Table, select
    from sqlalchemy.orm import registry

    table = Table("t", registry().metadata, Column("id", Integer), Column("name", String))
    sort = SortParams.parse("name", allowed=("name",), default="name")
    stmt = sort.apply(select(table), {"name": table.c.name}, tiebreaker=table.c.id)
    compiled = str(stmt).replace("\n", " ")
    assert "ORDER BY t.name ASC, t.id ASC" in compiled


def test_tiebreaker_follows_the_direction_of_the_last_sort_key():
    from sqlalchemy import Column, Integer, String, Table, select
    from sqlalchemy.orm import registry

    table = Table("t2", registry().metadata, Column("id", Integer), Column("name", String))
    sort = SortParams.parse("-name", allowed=("name",), default="name")
    stmt = sort.apply(select(table), {"name": table.c.name}, tiebreaker=table.c.id)
    assert "ORDER BY t2.name DESC, t2.id DESC" in str(stmt).replace("\n", " ")


def test_sort_rejects_fields_outside_the_whitelist():
    with pytest.raises(InputValidationError) as exc_info:
        SortParams.parse("password", allowed=("name",), default="name")
    assert exc_info.value.extra["allowed_sort_fields"] == ["name"]
