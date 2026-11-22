import dataclasses

import pymupdf
import pytest

from core.tools.contract import (
    ErrorDetail,
    Tool,
    ToolError,
    ToolInput,
    ToolResult,
)
from core.tools.document_reader import (
    DocumentReadError,
    DocumentReadResult,
    LocalDocumentReader,
)
from core.tools.extract_text import ExtractTextTool
from core.tools.text_statistics import TextStatisticsTool


def make_pdf(pages):
    document = pymupdf.open()
    for text in pages:
        page = document.new_page()
        if text:
            page.insert_text((72, 72), text)
    data = document.tobytes()
    document.close()
    return data


def make_input(ref, media_type="text/plain", options=None, filename="doc"):
    return ToolInput(
        job_id="job-1",
        document_ref=ref,
        filename=filename,
        media_type=media_type,
        options={} if options is None else options,
    )


class FakeReader:
    """Returns a prepared result or raises a prepared exception."""

    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def read(self, document_ref):
        self.calls.append(document_ref)
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def storage(tmp_path):
    def put(name, data):
        (tmp_path / name).write_bytes(data)
        return name

    put.reader = LocalDocumentReader(tmp_path)
    return put


# ---- contract -------------------------------------------------------------


def test_tools_implement_tool_interface():
    reader = FakeReader()

    for tool in (ExtractTextTool(reader), TextStatisticsTool(reader)):
        assert isinstance(tool, Tool)

    assert ExtractTextTool(reader).name == "extract_text"
    assert TextStatisticsTool(reader).name == "text_statistics"


def test_success_result_invariants():
    result = ToolResult.success({"x": 1})

    assert result.ok is True and result.data == {"x": 1} and result.error is None
    with pytest.raises(ValueError):
        ToolResult(ok=True, data=None, error=None)
    with pytest.raises(ValueError):
        ToolResult(ok=True, data={}, error=ToolError("E", "m"))


def test_failure_result_invariants():
    result = ToolResult.failure("E", "message", [ErrorDetail("f", "bad")])

    assert result.ok is False and result.data is None
    assert result.error == ToolError("E", "message", (ErrorDetail("f", "bad"),))
    with pytest.raises(ValueError):
        ToolResult(ok=False, data=None, error=None)
    with pytest.raises(ValueError):
        ToolResult(ok=False, data={}, error=ToolError("E", "m"))


def test_result_to_dict_matches_contract_format():
    ok = ToolResult.success({"text": "t", "page_count": None, "format": "txt"})
    failed = ToolResult.failure("DOCUMENT_CORRUPTED", "damaged")

    assert ok.to_dict() == {
        "ok": True,
        "data": {"text": "t", "page_count": None, "format": "txt"},
        "error": None,
    }
    assert failed.to_dict() == {
        "ok": False,
        "data": None,
        "error": {"code": "DOCUMENT_CORRUPTED", "message": "damaged", "details": []},
    }


def test_contract_structures_are_immutable():
    with pytest.raises(dataclasses.FrozenInstanceError):
        ToolResult.success({}).ok = False
    with pytest.raises(dataclasses.FrozenInstanceError):
        make_input("r").document_ref = "other"


# ---- extract_text ---------------------------------------------------------


def test_extract_text_from_txt(storage):
    ref = storage("a.txt", "Привет, мир".encode("utf-8"))

    result = ExtractTextTool(storage.reader).execute(make_input(ref))

    assert result.ok
    assert result.data == {"text": "Привет, мир", "page_count": None, "format": "txt"}


def test_extract_text_from_pdf(storage):
    ref = storage("a.pdf", make_pdf(["Hello PDF", "Page two"]))

    result = ExtractTextTool(storage.reader).execute(
        make_input(ref, "application/pdf")
    )

    assert result.ok
    assert result.data["format"] == "pdf"
    assert result.data["page_count"] == 2
    assert "Hello PDF" in result.data["text"] and "Page two" in result.data["text"]


def test_extract_text_uses_shared_reader():
    reader = FakeReader(DocumentReadResult("some text", None, "txt"))

    result = ExtractTextTool(reader).execute(make_input("documents/1"))

    assert reader.calls == ["documents/1"]
    assert result.data["text"] == "some text"


# ---- text_statistics ------------------------------------------------------


def test_statistics_for_txt(storage):
    text = "one two  three\nfour"
    ref = storage("a.txt", text.encode("utf-8"))

    result = TextStatisticsTool(storage.reader).execute(make_input(ref))

    assert result.ok
    assert result.data == {
        "word_count": 4,
        "character_count": len(text),
        "page_count": None,
    }


def test_statistics_counts_unicode_code_points_with_whitespace():
    reader = FakeReader(DocumentReadResult("Привет мир\n", None, "txt"))

    result = TextStatisticsTool(reader).execute(make_input("r"))

    assert result.data["word_count"] == 2
    assert result.data["character_count"] == 11


def test_statistics_for_pdf_includes_page_count(storage):
    ref = storage("a.pdf", make_pdf(["alpha beta", "gamma", "delta"]))

    result = TextStatisticsTool(storage.reader).execute(
        make_input(ref, "application/pdf")
    )

    assert result.ok
    assert result.data["page_count"] == 3
    assert result.data["word_count"] == 4


# ---- errors (both tools) --------------------------------------------------

TOOLS = [ExtractTextTool, TextStatisticsTool]


@pytest.mark.parametrize("tool_class", TOOLS)
def test_corrupted_pdf(tool_class, storage):
    ref = storage("bad.pdf", b"%PDF-1.4\nnot a pdf")

    result = tool_class(storage.reader).execute(make_input(ref, "application/pdf"))

    assert not result.ok
    assert result.error.code == "DOCUMENT_CORRUPTED"


@pytest.mark.parametrize("tool_class", TOOLS)
def test_pdf_without_extractable_text(tool_class, storage):
    ref = storage("scan.pdf", make_pdf([""]))

    result = tool_class(storage.reader).execute(make_input(ref, "application/pdf"))

    assert not result.ok
    assert result.error.code == "TEXT_NOT_FOUND"


@pytest.mark.parametrize("tool_class", TOOLS)
def test_empty_txt_has_no_text(tool_class, storage):
    ref = storage("empty.txt", b"  \n\t ")

    result = tool_class(storage.reader).execute(make_input(ref))

    assert result.error.code == "TEXT_NOT_FOUND"


@pytest.mark.parametrize("tool_class", TOOLS)
def test_document_read_failure(tool_class, storage):
    result = tool_class(storage.reader).execute(make_input("documents/missing"))

    assert not result.ok
    assert result.error.code == "DOCUMENT_READ_FAILED"


@pytest.mark.parametrize("tool_class", TOOLS)
def test_reader_os_error_becomes_read_failure(tool_class):
    reader = FakeReader(error=PermissionError(13, "Permission denied"))

    result = tool_class(reader).execute(make_input("r"))

    assert result.error.code == "DOCUMENT_READ_FAILED"


@pytest.mark.parametrize("tool_class", TOOLS)
def test_reader_error_code_is_passed_through(tool_class):
    reader = FakeReader(error=DocumentReadError("UNSUPPORTED_FORMAT", "nope"))

    result = tool_class(reader).execute(make_input("r"))

    assert result.error.code == "UNSUPPORTED_FORMAT"


@pytest.mark.parametrize("tool_class", TOOLS)
def test_unsupported_media_type(tool_class):
    reader = FakeReader(DocumentReadResult("text", None, "txt"))

    result = tool_class(reader).execute(make_input("r", "application/x-msdownload"))

    assert result.error.code == "UNSUPPORTED_FORMAT"
    assert reader.calls == []


@pytest.mark.parametrize("tool_class", TOOLS)
def test_unknown_option_names_the_field(tool_class):
    reader = FakeReader(DocumentReadResult("text", None, "txt"))

    result = tool_class(reader).execute(make_input("r", options={"language": "ru"}))

    assert not result.ok
    assert result.error.code == "VALIDATION_ERROR"
    assert result.error.details == (ErrorDetail("options", "Unknown option: language"),)
    assert reader.calls == []  # invalid parameters are rejected before reading


@pytest.mark.parametrize("tool_class", TOOLS)
def test_each_unknown_option_is_reported(tool_class):
    reader = FakeReader(DocumentReadResult("text", None, "txt"))

    result = tool_class(reader).execute(make_input("r", options={"b": 1, "a": 2}))

    assert [d.issue for d in result.error.details] == [
        "Unknown option: a",
        "Unknown option: b",
    ]


@pytest.mark.parametrize("tool_class", TOOLS)
@pytest.mark.parametrize("options", [None, [], "x", 5])
def test_options_must_be_an_object(tool_class, options):
    reader = FakeReader(DocumentReadResult("text", None, "txt"))
    tool_input = dataclasses.replace(make_input("r"), options=options)

    result = tool_class(reader).execute(tool_input)

    assert result.error.code == "VALIDATION_ERROR"
    assert result.error.details[0].field == "options"
