"""Tests for Dispatcher using the real ToolInput contract."""

from types import SimpleNamespace

import pytest

from core.dispatcher import Dispatcher
from core.errors import InvalidJobTransitionError, UnknownOperationError
from core.job import Job, JobStatus
from core.registry import ToolRegistry
from core.tools.contract import ToolInput
from core.tools.contract import ToolError, ToolResult
from core.tools.document_reader import LocalDocumentReader
from core.tools.extract_text import ExtractTextTool
from core.tools.text_statistics import TextStatisticsTool


class RecordingTool:
    """Fake Tool: returns a prepared ToolResult, records its input."""

    def __init__(self, name, result):
        self.name = name
        self._result = result
        self.received_input = None

    def execute(self, tool_input):
        self.received_input = tool_input
        return self._result


class CrashingTool:
    """Fake Tool: raises an unexpected exception."""

    def __init__(self, name):
        self.name = name

    def execute(self, tool_input):
        raise RuntimeError("boom")


def create_job(operation="extract_text") -> Job:
    return Job(
        operation=operation,
        document_ref="documents/test.txt",
        filename="test.txt",
        media_type="text/plain",
    )


def success_result(data=None):
    return SimpleNamespace(
        ok=True,
        data=data if data is not None else {"text": "Hello", "page_count": 1, "format": "txt"},
        error=None,
    )


def error_result(code="DOCUMENT_CORRUPTED"):
    return SimpleNamespace(
        ok=False,
        data=None,
        error={"code": code, "message": "Tool failed.", "details": []},
    )


def create_dispatcher(*tools) -> Dispatcher:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return Dispatcher(registry)


def test_unknown_operation_rejected_before_start():
    dispatcher = create_dispatcher()
    job = create_job(operation="ocr")

    with pytest.raises(UnknownOperationError):
        dispatcher.dispatch(job)

    assert job.status == JobStatus.CREATED
    assert job.history == (JobStatus.CREATED,)


def test_successful_execution_completes_job():
    tool = RecordingTool("extract_text", success_result({"text": "Hello"}))
    dispatcher = create_dispatcher(tool)
    job = create_job()

    result = dispatcher.dispatch(job)

    assert result.ok is True
    assert job.status == JobStatus.DONE
    assert job.result == {"text": "Hello"}
    assert job.history == (JobStatus.CREATED, JobStatus.RUNNING, JobStatus.DONE)


def test_tool_receives_documented_input():
    tool = RecordingTool("extract_text", success_result())
    dispatcher = create_dispatcher(tool)
    job = create_job()

    dispatcher.dispatch(job)

    tool_input = tool.received_input

    assert isinstance(tool_input, ToolInput)
    assert tool_input.job_id == job.id
    assert tool_input.document_ref == "documents/test.txt"
    assert tool_input.filename == "test.txt"
    assert tool_input.media_type == "text/plain"
    assert tool_input.options == {}


def test_tool_error_fails_job():
    tool = RecordingTool("extract_text", error_result("DOCUMENT_CORRUPTED"))
    dispatcher = create_dispatcher(tool)
    job = create_job()

    result = dispatcher.dispatch(job)

    assert result.ok is False
    assert job.status == JobStatus.FAILED
    assert job.error["code"] == "DOCUMENT_CORRUPTED"
    assert job.result is None


def test_unexpected_tool_exception_fails_job_with_internal_error():
    dispatcher = create_dispatcher(CrashingTool("extract_text"))
    job = create_job()

    result = dispatcher.dispatch(job)

    assert result.ok is False
    assert job.status == JobStatus.FAILED
    assert job.error["code"] == "INTERNAL_ERROR"
    assert "boom" in job.error["message"]


def test_new_tool_works_without_dispatcher_changes():
    extract_tool = RecordingTool("extract_text", success_result())
    statistics_tool = RecordingTool(
        "text_statistics",
        success_result({"word_count": 2, "character_count": 11, "page_count": None}),
    )
    dispatcher = create_dispatcher(extract_tool, statistics_tool)

    job = create_job(operation="text_statistics")
    result = dispatcher.dispatch(job)

    assert result.ok is True
    assert job.status == JobStatus.DONE
    assert job.result["word_count"] == 2


def test_dispatch_propagates_invalid_job_state():
    tool = RecordingTool("extract_text", success_result())
    dispatcher = create_dispatcher(tool)
    job = create_job()
    job.start()
    job.complete({"text": "Already done"})

    with pytest.raises(InvalidJobTransitionError):
        dispatcher.dispatch(job)

    assert job.status == JobStatus.DONE
    assert job.result == {"text": "Already done"}


def test_dispatch_with_real_text_statistics_tool(tmp_path):
    text = "Привет мир\n"

    documents_dir = tmp_path / "documents"
    documents_dir.mkdir()

    (documents_dir / "test.txt").write_bytes(
        text.encode("utf-8")
    )

    reader = LocalDocumentReader(tmp_path)
    tool = TextStatisticsTool(reader)
    dispatcher = create_dispatcher(tool)

    job = create_job(operation="text_statistics")

    result = dispatcher.dispatch(job)

    assert isinstance(result, ToolResult)
    assert result.ok is True
    assert job.status == JobStatus.DONE
    assert job.result == {
        "word_count": 2,
        "character_count": len(text),
        "page_count": None,
    }


def test_dispatch_with_real_tool_error(tmp_path):
    documents_dir = tmp_path / "documents"
    documents_dir.mkdir()

    (documents_dir / "test.txt").write_bytes(
        "  \n".encode("utf-8")
    )

    reader = LocalDocumentReader(tmp_path)
    tool = ExtractTextTool(reader)
    dispatcher = create_dispatcher(tool)

    job = create_job()

    result = dispatcher.dispatch(job)

    assert isinstance(result, ToolResult)
    assert result.ok is False

    assert job.status == JobStatus.FAILED
    assert isinstance(job.error, ToolError)
    assert job.error.code == "TEXT_NOT_FOUND"
