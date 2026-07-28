from types import SimpleNamespace
import uuid

import pytest

from funart_prompt_id_compat.prompt_id_compat import install_prompt_id_compat


CANONICAL_UUID = "123e4567-e89b-12d3-a456-426614174000"
FC_REQUEST_ID = "1-6a603c38-1525c9f1-9b1542799d80"


def _uuid_only(value):
    """Match ComfyUI v0.27.0's canonical UUID validator."""
    if not isinstance(value, str):
        raise ValueError("job id must be a string")
    if str(uuid.UUID(value)) != value:
        raise ValueError("job id must be a canonical UUID")
    return value


@pytest.mark.parametrize("task_id", [FC_REQUEST_ID, "my-task-001", CANONICAL_UUID])
def test_preserves_task_id_across_server_and_jobs_aliases(task_id):
    server = SimpleNamespace(validate_job_id=_uuid_only)
    jobs = SimpleNamespace(validate_job_id=_uuid_only)

    assert install_prompt_id_compat(server, jobs) is True
    assert server.validate_job_id(task_id) == task_id
    assert jobs.validate_job_id(task_id) == task_id

    # Queue/history/status/cancel all use the prompt id as an exact-match key.
    # Both aliases must therefore produce the same original FC identifier.
    stored = {server.validate_job_id(task_id): "queued"}
    assert stored[jobs.validate_job_id(task_id)] == "queued"


def test_rejects_values_that_cannot_be_task_ids():
    server = SimpleNamespace(validate_job_id=_uuid_only)
    jobs = SimpleNamespace(validate_job_id=_uuid_only)
    install_prompt_id_compat(server, jobs)

    with pytest.raises(ValueError):
        server.validate_job_id(123)
    with pytest.raises(ValueError):
        server.validate_job_id("")


def test_install_is_idempotent():
    server = SimpleNamespace(validate_job_id=_uuid_only)
    jobs = SimpleNamespace(validate_job_id=_uuid_only)

    assert install_prompt_id_compat(server, jobs) is True
    installed_validator = server.validate_job_id
    assert install_prompt_id_compat(server, jobs) is False
    assert server.validate_job_id is installed_validator
    assert jobs.validate_job_id is installed_validator


def test_leaves_older_permissive_validator_unchanged():
    def permissive(value):
        return value

    server = SimpleNamespace(validate_job_id=permissive)

    assert install_prompt_id_compat(server) is False
    assert server.validate_job_id is permissive


def test_skips_versions_without_job_id_validator():
    assert install_prompt_id_compat(SimpleNamespace()) is False
