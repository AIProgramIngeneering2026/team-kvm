import pytest

from core.errors import DuplicateToolError, UnknownOperationError
from core.registry import ToolRegistry


class FakeTool:
    def __init__(self, name):
        self.name = name


def create_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(FakeTool("extract_text"))
    return registry


def test_register_and_get_tool():
    registry = create_registry()
    tool = FakeTool("text_statistics")

    registry.register(tool)

    assert registry.get("text_statistics") is tool
    assert registry.get("extract_text").name == "extract_text"


def test_get_unknown_operation_raises():
    registry = create_registry()

    with pytest.raises(UnknownOperationError) as exc_info:
        registry.get("ocr")

    assert exc_info.value.operation == "ocr"
    assert "ocr" in str(exc_info.value)


def test_register_duplicate_name_raises():
    registry = create_registry()

    with pytest.raises(DuplicateToolError):
        registry.register(FakeTool("extract_text"))

    # The original tool is still registered, not overwritten.
    assert registry.get("extract_text").__class__ is FakeTool


def test_register_tool_without_name_raises():
    registry = ToolRegistry()

    with pytest.raises(ValueError):
        registry.register(object())


def test_operations_lists_registered_names():
    registry = create_registry()
    registry.register(FakeTool("text_statistics"))

    assert registry.operations() == ("extract_text", "text_statistics")


def test_new_tool_does_not_affect_existing_ones():
    registry = create_registry()
    extract_tool = registry.get("extract_text")

    registry.register(FakeTool("text_statistics"))

    assert registry.get("extract_text") is extract_tool
