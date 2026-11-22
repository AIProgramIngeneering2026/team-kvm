"""Common Tool contract (see docs/tool-contract.md).

Defines the ``Tool`` interface and the data structures exchanged between the
Dispatcher and a Tool: ``ToolInput``, ``ToolResult``, ``ToolError`` and
``ErrorDetail``.

A Tool knows nothing about HTTP, the database or Job state: it receives a
``ToolInput`` and returns a ``ToolResult``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

# Error codes a Tool may return (docs/tool-contract.md, sections 7 and 8).
VALIDATION_ERROR = "VALIDATION_ERROR"
UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
DOCUMENT_CORRUPTED = "DOCUMENT_CORRUPTED"
TEXT_NOT_FOUND = "TEXT_NOT_FOUND"
DOCUMENT_READ_FAILED = "DOCUMENT_READ_FAILED"

SUPPORTED_MEDIA_TYPES = ("application/pdf", "text/plain")


@dataclass(frozen=True)
class ErrorDetail:
    """Which field is wrong and why."""

    field: str
    issue: str

    def to_dict(self) -> dict[str, str]:
        return {"field": self.field, "issue": self.issue}


@dataclass(frozen=True)
class ToolError:
    """Machine-readable error returned by a Tool."""

    code: str
    message: str
    details: tuple[ErrorDetail, ...] = ()

    def __post_init__(self) -> None:
        # Accept any iterable of details but always store an immutable tuple.
        object.__setattr__(self, "details", tuple(self.details))

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": [detail.to_dict() for detail in self.details],
        }


@dataclass(frozen=True)
class ToolInput:
    """Input the Dispatcher passes to a Tool.

    ``document_ref`` is an opaque reference to the stored document; it is not
    a file path and ``filename`` must never be used as one.
    """

    job_id: str
    document_ref: str
    filename: str
    media_type: str
    options: Mapping[str, object]


@dataclass(frozen=True)
class ToolResult:
    """Outcome of ``Tool.execute``.

    Invariants (docs/tool-contract.md, section 4):
      * ``ok`` is True  -> ``data`` is set, ``error`` is None;
      * ``ok`` is False -> ``data`` is None, ``error`` is set.
    """

    ok: bool
    data: dict[str, Any] | None = None
    error: ToolError | None = None

    def __post_init__(self) -> None:
        if self.ok:
            if self.data is None or self.error is not None:
                raise ValueError("Successful ToolResult needs data and no error")
        else:
            if self.data is not None or self.error is None:
                raise ValueError("Failed ToolResult needs an error and no data")

    @classmethod
    def success(cls, data: dict[str, Any]) -> ToolResult:
        return cls(ok=True, data=data, error=None)

    @classmethod
    def failure(
        cls,
        code: str,
        message: str,
        details: tuple[ErrorDetail, ...] | list[ErrorDetail] = (),
    ) -> ToolResult:
        return cls(
            ok=False, data=None, error=ToolError(code, message, tuple(details))
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "data": self.data,
            "error": self.error.to_dict() if self.error else None,
        }


@runtime_checkable
class Tool(Protocol):
    """Interface every document-processing Tool implements."""

    name: str

    def execute(self, input: ToolInput) -> ToolResult:
        """Run the operation. Domain errors are returned, not raised."""
        ...


def validate_options(options: object) -> list[ErrorDetail]:
    """Validate ``ToolInput.options`` for MVP operations.

    In the MVP ``options`` must be an empty mapping. Returns the list of
    problems (empty when valid); every problem names the offending field.
    """
    if not isinstance(options, Mapping):
        return [ErrorDetail("options", "Options must be an object.")]
    return [
        ErrorDetail("options", f"Unknown option: {key}") for key in sorted(options, key=str)
    ]


def validation_failure(details: list[ErrorDetail]) -> ToolResult:
    """Build the ``VALIDATION_ERROR`` result for invalid Tool parameters."""
    return ToolResult.failure(
        VALIDATION_ERROR, "The Tool parameters are invalid.", details
    )
