"""TextStatisticsTool: the ``text_statistics`` operation.

Counting rules (docs/tool-contract.md, section 6.2):
  * words: ``len(text.split())``;
  * characters: ``len(text)`` (Unicode code points, whitespace included);
  * pages: PDF page count from the DocumentReader, ``None`` for TXT.
"""

from core.tools.contract import ToolInput, ToolResult
from core.tools.document_reader import DocumentReader, read_for_tool


class TextStatisticsTool:
    name = "text_statistics"

    def __init__(self, reader: DocumentReader):
        self._reader = reader

    def execute(self, input: ToolInput) -> ToolResult:
        document = read_for_tool(self._reader, input)
        if isinstance(document, ToolResult):
            return document
        return ToolResult.success(
            {
                "word_count": len(document.text.split()),
                "character_count": len(document.text),
                "page_count": document.page_count,
            }
        )
