from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4
from threading import RLock
from copy import deepcopy

from core.errors import InvalidJobTransitionError


class JobStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"

ALLOWED_TRANSITIONS = {
    JobStatus.CREATED: {JobStatus.RUNNING},
    JobStatus.RUNNING: {
        JobStatus.DONE,
        JobStatus.FAILED,
    },
    JobStatus.DONE: set(),
    JobStatus.FAILED: set(),
}

class Job:
    def __init__(
        self,
        operation: str,
        document_ref: str,
        filename: str,
        media_type: str,
        options: dict[str, object] | None = None,
    ):
        self.id = str(uuid4())
        self._lock = RLock()
        self.operation = operation
        self.document_ref = document_ref
        self.filename = filename
        self.media_type = media_type
        self.options = options.copy() if options is not None else {}

        self._status = JobStatus.CREATED
        self._result: object | None = None
        self._error: object | None = None

        self.created_at = datetime.now(timezone.utc)
        self.updated_at = self.created_at

        self._history = [JobStatus.CREATED]

    @property
    def status(self) -> JobStatus:
        with self._lock:
            return self._status

    @property
    def result(self) -> object | None:
        with self._lock:
            return deepcopy(self._result)

    @property
    def error(self) -> object | None:
        with self._lock:
            return deepcopy(self._error)

    @property
    def history(self) -> tuple[JobStatus, ...]:
        with self._lock:
            return tuple(self._history)

    def _transition(self, target: JobStatus) -> None:
        self._validate_transition(target)

        self._status = target
        self.updated_at = datetime.now(timezone.utc)
        self._history.append(target)

    def _validate_transition(self, target: JobStatus) -> None:
        if target not in ALLOWED_TRANSITIONS[self._status]:
            raise InvalidJobTransitionError(
                current_status=self._status.value,
                target_status=target.value,
            )

    def start(self) -> None:
        with self._lock:
            self._transition(JobStatus.RUNNING)

    def complete(self, result: object) -> None:
        with self._lock:
            self._validate_transition(JobStatus.DONE)

            if result is None:
                raise ValueError("Job result cannot be None")

            result_copy = deepcopy(result)

            self._transition(JobStatus.DONE)
            self._result = result_copy


    def fail(self, error: object) -> None:
        with self._lock:
            self._validate_transition(JobStatus.FAILED)

            if error is None:
                raise ValueError("Job error cannot be None")

            error_copy = deepcopy(error)

            self._transition(JobStatus.FAILED)
            self._error = error_copy

    def recover_after_restart(self) -> None:
        with self._lock:
            if self._status == JobStatus.RUNNING:
                self.fail({
                    "code": "WORKER_INTERRUPTED",
                    "message": "Job execution was interrupted by a server restart.",
                    "details": [],
                })