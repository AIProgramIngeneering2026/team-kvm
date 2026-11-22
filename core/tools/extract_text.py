"""ExtractTextTool: the ``extract_text`` operation."""

from core.tools.contract import ToolInput, ToolResult
from core.tools.document_reader import DocumentReader, read_for_tool


class ExtractTextTool:
    name = "extract_text"

    def __init__(self, reader: DocumentReader):
        self._reader = reader

    def execute(self, input: ToolInput) -> ToolResult:
        document = read_for_tool(self._reader, input)
        if isinstance(document, ToolResult):
            return document
        return ToolResult.success(
            {
                "text": document.text,
                "page_count": document.page_count,
                "format": document.format,
            }
        )
