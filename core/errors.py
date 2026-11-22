class InvalidJobTransitionError(Exception):
    code = "INVALID_JOB_TRANSITION"

    def __init__(self, current_status: str, target_status: str):
        self.current_status = current_status
        self.target_status = target_status

        super().__init__(
            f"Transition from '{current_status}' "
            f"to '{target_status}' is not allowed"
        )

class UnknownOperationError(Exception):
    code = "UNKNOWN_OPERATION"

    def __init__(self, operation: str):
        self.operation = operation

        super().__init__(f"Unknown operation: '{operation}'")

class DuplicateToolError(Exception):
    code = "DUPLICATE_TOOL"

    def __init__(self, name: str):
        self.name = name

        super().__init__(f"A tool is already registered for '{name}'")
