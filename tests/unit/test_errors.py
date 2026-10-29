"""The error model produces valid RFC 9457 problem documents."""

from __future__ import annotations

from app.core.errors import AppError, ConflictError, NotFoundError


def test_problem_document_shape():
    problem = NotFoundError.for_resource("Pet", "abc").to_problem(instance="/api/v1/pets/abc")
    assert problem["status"] == 404
    assert problem["code"] == "not_found"
    assert problem["type"].endswith("/not_found")
    assert problem["instance"] == "/api/v1/pets/abc"
    assert problem["resource"] == "Pet"


def test_extra_members_are_merged_not_nested():
    problem = ConflictError("nope", extra={"constraint": "uq_pets_name"}).to_problem()
    assert problem["constraint"] == "uq_pets_name"


def test_subclasses_keep_their_own_code():
    class QuotaExceededError(AppError):
        status_code = 429
        code = "quota_exceeded"
        title = "Too Many Requests"

    assert QuotaExceededError().to_problem()["code"] == "quota_exceeded"
