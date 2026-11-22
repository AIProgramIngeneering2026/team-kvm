"""Dispatcher: drives Job execution through registered Tools.

The Dispatcher knows only the Tool interface (``name`` / ``execute(input)``)
from docs/tool-contract.md. It never references concrete Tool classes:
new operations are added by registering a new Tool in the ToolRegistry.

Lifecycle (see docs/architecture.md and ADR-0002):
    - the Job is started (the Job itself validates the transition);
    - the Tool resolved by ``job.operation`` is executed;
    - a successful ToolResult completes the Job with ``result.data``;
    - a failed ToolResult fails the Job with ``result.error``;
    - an unexpected exception inside the Tool fails the Job with
      ``INTERNAL_ERROR`` (ADR-0002, item 4).
"""

from types import SimpleNamespace

from core.job import Job
from core.registry import ToolRegistry


def _build_tool_input(job: Job):
    """Build ToolInput for the Tool from the stored Job data.

    Imported lazily so the Dispatcher module itself stays decoupled from
    the tools package; the real ToolInput lives in core/tools/contract.py.
    """
    from core.tools.contract import ToolInput

    return ToolInput(
        job_id=job.id,
        document_ref=job.document_ref,
        filename=job.filename,
        media_type=job.media_type,
        options=job.options,
    )


class Dispatcher:
    """Resolves Tools via the registry and executes Jobs with them."""

    def __init__(self, registry: ToolRegistry):
        self._registry = registry

    def dispatch(self, job: Job):
        """Execute the Job with the Tool registered for its operation.

        Returns the ToolResult (or an error result for an unexpected
        exception). Raises UnknownOperationError when no Tool is
        registered for ``job.operation``; the Job is not started then.
        Invalid Job state transitions are propagated from the Job itself.
        """
        tool = self._registry.get(job.operation)

        job.start()

        try:
            result = tool.execute(_build_tool_input(job))
        except Exception as exc:
            error = {
                "code": "INTERNAL_ERROR",
                "message": f"Tool raised an unexpected exception: {exc}",
                "details": [],
            }
            job.fail(error)
            return SimpleNamespace(ok=False, data=None, error=error)

        if result.ok:
            job.complete(result.data)
        else:
            job.fail(result.error)

        return result
