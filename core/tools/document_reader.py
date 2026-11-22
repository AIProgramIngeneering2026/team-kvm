"""DocumentReader: the single place where PDF and TXT files are read.

Hides PyMuPDF, UTF-8 decoding and the physical storage location from Tools
(docs/tool-contract.md, section 5). It does not count words or characters.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

import pymupdf

from core.tools.contract import (
    DOCUMENT_CORRUPTED,
    DOCUMENT_READ_FAILED,
    SUPPORTED_MEDIA_TYPES,
    TEXT_NOT_FOUND,
    UNSUPPORTED_FORMAT,
    ErrorDetail,
    ToolInput,
    ToolResult,
    validate_options,
    validation_failure,
)

_PDF_MAGIC = b"%PDF-"
_PDF_MAGIC_WINDOW = 1024  # the header may be preceded by a few bytes


@dataclass(frozen=True)
class DocumentReadResult:
    """Text and metadata of a read document."""

    text: str
    page_count: int | None  # PDF page count; None for TXT
    format: Literal["pdf", "txt"]


class DocumentReadError(Exception):
    """A document cannot be read; ``code`` is a Tool error code."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class DocumentReader(Protocol):
    def read(self, document_ref: str) -> DocumentReadResult:
        """Read the document or raise ``DocumentReadError``."""
        ...


class LocalDocumentReader:
    """Reads documents stored as files under ``root``.

    ``document_ref`` is a path relative to ``root`` (for example
    ``documents/<job id>``). References that leave ``root`` are rejected.
    """

    def __init__(self, root: str | Path):
        self._root = Path(root).resolve()

    def read(self, document_ref: str) -> DocumentReadResult:
        data = self._load_bytes(document_ref)
        if _PDF_MAGIC in data[:_PDF_MAGIC_WINDOW]:
            return self._read_pdf(data)
        return self._read_txt(data)

    def _load_bytes(self, document_ref: str) -> bytes:
        path = (self._root / document_ref).resolve()
        if not path.is_relative_to(self._root):
            raise DocumentReadError(
                DOCUMENT_READ_FAILED, "Document reference is outside the storage."
            )
        try:
            return path.read_bytes()
        except OSError as exc:
            raise DocumentReadError(
                DOCUMENT_READ_FAILED, f"The document cannot be read: {exc.strerror}."
            ) from exc

    @staticmethod
    def _read_pdf(data: bytes) -> DocumentReadResult:
        try:
            with pymupdf.open(stream=data, filetype="pdf") as document:
                if document.needs_pass:
                    raise DocumentReadError(
                        DOCUMENT_READ_FAILED, "The PDF document is password-protected."
                    )
                page_count = document.page_count
                if page_count < 1:
                    raise DocumentReadError(
                        DOCUMENT_CORRUPTED, "The PDF document has no pages."
                    )
                text = "\n".join(page.get_text() for page in document)
        except DocumentReadError:
            raise
        except Exception as exc:  # PyMuPDF raises several unrelated types
            raise DocumentReadError(
                DOCUMENT_CORRUPTED, "The PDF document is damaged or cannot be parsed."
            ) from exc
        return DocumentReadResult(text=text, page_count=page_count, format="pdf")

    @staticmethod
    def _read_txt(data: bytes) -> DocumentReadResult:
        try:
            # utf-8-sig is UTF-8 that also drops a leading BOM.
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DocumentReadError(
                UNSUPPORTED_FORMAT, "Only PDF and UTF-8 TXT files are supported."
            ) from exc
        return DocumentReadResult(text=text, page_count=None, format="txt")


def read_for_tool(
    reader: DocumentReader, tool_input: ToolInput
) -> DocumentReadResult | ToolResult:
    """Shared first steps of every MVP Tool.

    Validates ``options`` and ``media_type``, reads the document and checks
    that it has extractable text. Returns the read document, or a failed
    ``ToolResult`` that the Tool returns as is.
    """
    problems = validate_options(tool_input.options)
    if problems:
        return validation_failure(problems)

    if tool_input.media_type not in SUPPORTED_MEDIA_TYPES:
        return ToolResult.failure(
            UNSUPPORTED_FORMAT,
            "Only PDF and UTF-8 TXT files are supported.",
            [ErrorDetail("media_type", f"Unsupported media type: {tool_input.media_type}")],
        )

    try:
        document = reader.read(tool_input.document_ref)
    except DocumentReadError as exc:
        return ToolResult.failure(exc.code, exc.message)
    except OSError as exc:
        return ToolResult.failure(
            DOCUMENT_READ_FAILED, f"The document cannot be read: {exc.strerror}."
        )

    if not document.text.strip():
        return ToolResult.failure(
            TEXT_NOT_FOUND, "The document contains no extractable text."
        )
    return document
