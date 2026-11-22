"""Tests for the Dispatcher.

core/tools/contract.py (with the real ToolInput) is implemented by another
teammate in parallel. Until it exists, tests inject a stub contract module
with the same documented ToolInput structure (see docs/tool-contract.md).
The stub is only used when the real module is absent.
"""

import sys
import types
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from core.dispatcher import Dispatcher
from core.errors import InvalidJobTransitionError, UnknownOperationError
from core.job import Job, JobStatus
from core.registry import ToolRegistry


@dataclass
class StubToolInput:
    job_id: str
    document_ref: str
    filename: str
    media_type: str
    options: dict = field(default_factory=dict)


if "core.tools.contract" not in sys.modules:
    _contract_stub = types.ModuleType("core.tools.contract")
    _contract_stub.ToolInput = StubToolInput
    sys.modules["core.tools.contract"] = _contract_stub


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
