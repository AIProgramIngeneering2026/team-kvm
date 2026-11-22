import pytest

from core.job import Job, JobStatus
from core.errors import InvalidJobTransitionError
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier


def create_job() -> Job:
    return Job(
        operation="extract_text",
        document_ref="documents/test.txt",
        filename="test.txt",
        media_type="text/plain",
    )


def test_job_created():
    job = create_job()

    assert job.status == JobStatus.CREATED
    assert job.result is None
    assert job.error is None


def test_successful_lifecycle():
    job = create_job()

    job.start()
    assert job.status == JobStatus.RUNNING

    job.complete({"text": "Hello, world!"})
    assert job.status == JobStatus.DONE
    assert job.result == {"text": "Hello, world!"}


def test_z1_double_start():
    job = create_job()
    job.start()

    with pytest.raises(InvalidJobTransitionError):
        job.start()

    assert job.status == JobStatus.RUNNING


def test_z4_failed_job_cannot_complete():
    job = create_job()

    job.start()
    job.fail({"code": "DOCUMENT_READ_FAILED"})

    with pytest.raises(InvalidJobTransitionError):
        job.complete({"text": "Hello"})

    assert job.status == JobStatus.FAILED


def test_z5_cannot_complete_without_start():
    job = create_job()

    with pytest.raises(InvalidJobTransitionError):
        job.complete({"text": "Hello"})

    assert job.status == JobStatus.CREATED


def test_z6_completed_job_cannot_restart():
    job = create_job()

    job.start()
    job.complete({"text": "Hello"})

    with pytest.raises(InvalidJobTransitionError):
        job.start()

    assert job.status == JobStatus.DONE


def test_invalid_transition_does_not_change_history():
    job = create_job()
    job.start()

    history_before = job.history

    with pytest.raises(InvalidJobTransitionError):
        job.start()

    assert job.history == history_before


def test_z2_restart_running_job():
    job = create_job()
    job.start()

    job.recover_after_restart()

    assert job.status == JobStatus.FAILED
    assert job.error["code"] == "WORKER_INTERRUPTED"
    assert job.history == (
        JobStatus.CREATED,
        JobStatus.RUNNING,
        JobStatus.FAILED,
    )


def test_restart_created_job():
    job = create_job()

    job.recover_after_restart()

    assert job.status == JobStatus.CREATED
    assert job.history == (JobStatus.CREATED,)


def test_restart_completed_job():
    job = create_job()
    job.start()
    job.complete({"text": "Hello"})

    job.recover_after_restart()

    assert job.status == JobStatus.DONE
    assert job.result == {"text": "Hello"}
    assert job.history == (
        JobStatus.CREATED,
        JobStatus.RUNNING,
        JobStatus.DONE,
    )


def test_late_finish_after_restart():
    job = create_job()
    job.start()
    job.recover_after_restart()

    with pytest.raises(InvalidJobTransitionError):
        job.complete({"text": "Late result"})

    assert job.status == JobStatus.FAILED
    assert job.result is None
    assert job.error["code"] == "WORKER_INTERRUPTED"


def test_cannot_fail_before_start():
    job = create_job()

    with pytest.raises(InvalidJobTransitionError):
        job.fail({"code": "DOCUMENT_READ_FAILED"})

    assert job.status == JobStatus.CREATED
    assert job.error is None


def test_cannot_complete_twice():
    job = create_job()
    job.start()
    job.complete({"text": "First result"})

    with pytest.raises(InvalidJobTransitionError):
        job.complete({"text": "Second result"})

    assert job.status == JobStatus.DONE
    assert job.result == {"text": "First result"}


def test_completed_job_cannot_fail():
    job = create_job()
    job.start()
    job.complete({"text": "Success"})

    with pytest.raises(InvalidJobTransitionError):
        job.fail({"code": "INTERNAL_ERROR"})

    assert job.status == JobStatus.DONE
    assert job.error is None


def test_failed_job_cannot_restart():
    job = create_job()
    job.start()
    job.fail({"code": "DOCUMENT_CORRUPTED"})

    with pytest.raises(InvalidJobTransitionError):
        job.start()

    assert job.status == JobStatus.FAILED


def test_recovery_does_not_change_failed_job():
    job = create_job()
    job.start()
    job.fail({"code": "DOCUMENT_CORRUPTED"})

    history_before = job.history

    job.recover_after_restart()

    assert job.status == JobStatus.FAILED
    assert job.error["code"] == "DOCUMENT_CORRUPTED"
    assert job.history == history_before


def test_none_result_is_rejected():
    job = create_job()
    job.start()

    with pytest.raises(ValueError):
        job.complete(None)

    assert job.status == JobStatus.RUNNING
    assert job.result is None


def test_none_error_is_rejected():
    job = create_job()
    job.start()

    with pytest.raises(ValueError):
        job.fail(None)

    assert job.status == JobStatus.RUNNING
    assert job.error is None


def test_z1_concurrent_start():
    job = create_job()
    barrier = Barrier(2)

    def try_start():
        barrier.wait(timeout=5)

        try:
            job.start()
            return "started"
        except InvalidJobTransitionError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(try_start)
            for _ in range(2)
        ]
        results = [
            future.result(timeout=5)
            for future in futures
        ]

    assert sorted(results) == ["rejected", "started"]

    assert job.status == JobStatus.RUNNING
    assert job.history == (
        JobStatus.CREATED,
        JobStatus.RUNNING,
    )


def test_completed_result_cannot_be_modified():
    job = create_job()
    job.start()

    original_result = {"text": "Original"}

    job.complete(original_result)

    original_result["text"] = "Changed"

    assert job.result == {"text": "Original"}

    returned_result = job.result
    returned_result["text"] = "Modified"

    assert job.result == {"text": "Original"}


def test_invalid_transition_has_priority():
    job = create_job()

    with pytest.raises(InvalidJobTransitionError):
        job.complete(None)

    assert job.status == JobStatus.CREATED


def test_copy_failure_preserves_job():
    class UncopyableResult:
        def __deepcopy__(self, memo):
            raise RuntimeError("Cannot copy result")

    job = create_job()
    job.start()

    history_before = job.history

    with pytest.raises(RuntimeError):
        job.complete(UncopyableResult())

    assert job.status == JobStatus.RUNNING
    assert job.result is None
    assert job.history == history_before