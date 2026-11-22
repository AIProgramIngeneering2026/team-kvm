class InvalidJobTransitionError(Exception):
    code = "INVALID_JOB_TRANSITION"

    def __init__(self, current_status: str, target_status: str):
        self.current_status = current_status
        self.target_status = target_status

        super().__init__(
            f"Transition from '{current_status}' "
            f"to '{target_status}' is not allowed"
        )