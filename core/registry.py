"""Registry of document-processing tools.

Maps operation names (e.g. ``extract_text``) to Tool implementations.
The Dispatcher looks tools up here and never knows concrete Tool classes.
See docs/tool-contract.md for the Tool interface contract.
"""

from core.errors import DuplicateToolError, UnknownOperationError


class ToolRegistry:
    """A simple name -> Tool mapping with duplicate protection."""

    def __init__(self):
        self._tools = {}

    def register(self, tool) -> None:
        """Register a Tool instance by its ``name`` attribute."""
        name = getattr(tool, "name", None)
        if not name:
            raise ValueError("Tool must have a non-empty 'name' attribute")
        if name in self._tools:
            raise DuplicateToolError(name)
        self._tools[name] = tool

    def get(self, operation: str):
        """Return the Tool registered for ``operation``.

        Raises UnknownOperationError if no Tool is registered.
        """
        try:
            return self._tools[operation]
        except KeyError:
            raise UnknownOperationError(operation) from None

    def operations(self) -> tuple:
        """Return the sorted names of all registered operations."""
        return tuple(sorted(self._tools))
