"""Pagination, sorting and the generic list envelope.

List endpoints are the one place where a response envelope earns its keep: clients need
the page metadata alongside the items. Everything else returns the resource directly.

Offset pagination is the default because it is what UIs with page numbers need and it
composes with arbitrary sorting. Keyset/cursor pagination is the documented escape hatch
for very large or high-churn collections (see docs/architecture.md).

One correctness rule is enforced rather than documented: **the ORDER BY must be a total
order.** ``ORDER BY name LIMIT 20 OFFSET 20`` over rows with duplicate names lets
Postgres return them in any order per query, so a client paging through the collection
silently sees some rows twice and never sees others. :meth:`SortParams.apply` therefore
always appends a unique tiebreaker column.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Self

from fastapi import Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import InputValidationError

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 20


@dataclass(frozen=True, slots=True)
class PageParams:
    """Offset/limit, taken from the query string via :data:`Pagination`."""

    limit: int = DEFAULT_PAGE_SIZE
    offset: int = 0

    @property
    def page_number(self) -> int:
        return self.offset // self.limit + 1


def _page_params(
    limit: Annotated[
        int,
        Query(ge=1, le=MAX_PAGE_SIZE, description="Maximum number of items to return."),
    ] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0, description="Number of items to skip.")] = 0,
) -> PageParams:
    return PageParams(limit=limit, offset=offset)


Pagination = Annotated[PageParams, Depends(_page_params)]


@dataclass(frozen=True, slots=True)
class SortParams:
    """Parsed ``?sort=-created_at,name`` ordering, validated against a whitelist."""

    fields: tuple[tuple[str, bool], ...] = ()  # (column_name, descending)

    @classmethod
    def parse(cls, raw: str | None, *, allowed: Sequence[str], default: str) -> Self:
        parsed: list[tuple[str, bool]] = []
        for token in (raw or default).split(","):
            token = token.strip()
            if not token:
                continue
            descending = token.startswith("-")
            name = token.lstrip("+-")
            if name not in allowed:
                raise InputValidationError(
                    f"Cannot sort by '{name}'.",
                    extra={"allowed_sort_fields": list(allowed)},
                )
            parsed.append((name, descending))
        return cls(tuple(parsed))

    def apply[T: Any](
        self,
        stmt: Select[T],
        columns: dict[str, Any],
        *,
        tiebreaker: Any,
    ) -> Select[T]:
        """Apply the ordering, always ending in a unique column.

        ``tiebreaker`` must be unique (normally the primary key). Without it, offset
        pagination over a non-unique sort key is not stable and pages overlap.
        """
        order = [
            columns[name].desc() if desc else columns[name].asc() for name, desc in self.fields
        ]
        descending_last = self.fields[-1][1] if self.fields else False
        order.append(tiebreaker.desc() if descending_last else tiebreaker.asc())
        return stmt.order_by(*order)


class PageMeta(BaseModel):
    total: int = Field(description="Total number of items matching the filters.")
    limit: int
    offset: int
    has_more: bool


class Page[T](BaseModel):
    """Generic list envelope. Use as ``-> Page[PetRead]`` on the route."""

    items: list[T]
    meta: PageMeta

    @classmethod
    def build(cls, items: Sequence[T], *, total: int, params: PageParams) -> Page[T]:
        return cls(
            items=list(items),
            meta=PageMeta(
                total=total,
                limit=params.limit,
                offset=params.offset,
                has_more=params.offset + len(items) < total,
            ),
        )


async def paginate[T: Any](
    session: AsyncSession,
    stmt: Select[tuple[T]],
    params: PageParams,
) -> tuple[Sequence[T], int]:
    """Run ``stmt`` for one page and count the full result set.

    Two queries rather than a window function: the count query drops ORDER BY and any
    eager-loading joins, which keeps it cheap and lets Postgres pick an index-only plan.
    """
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = (await session.execute(count_stmt)).scalar_one()
    if total == 0:
        return [], 0
    result = await session.execute(stmt.limit(params.limit).offset(params.offset))
    return result.scalars().all(), total
