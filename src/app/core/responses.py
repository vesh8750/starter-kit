"""Response classes.

``orjson`` is used for serialisation because it is measurably faster than the stdlib
encoder and handles ``datetime``/``UUID`` natively, which this API returns constantly.
"""

from __future__ import annotations

from typing import Any

import orjson
from starlette.responses import JSONResponse


class ORJSONResponse(JSONResponse):
    media_type = "application/json"

    def render(self, content: Any) -> bytes:
        return orjson.dumps(content)


class ProblemJSONResponse(ORJSONResponse):
    """RFC 9457 problem details. Distinct media type so clients can branch on it."""

    media_type = "application/problem+json"
