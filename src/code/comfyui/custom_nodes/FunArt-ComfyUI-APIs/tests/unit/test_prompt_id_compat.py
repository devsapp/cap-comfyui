from types import SimpleNamespace

import pytest

from prompt_id_compat import install_prompt_id_compat


def _uuid_only(value):
    if value != "123e4567-e89b-12d3-a456-426614174000":
        raise ValueError("UUID required")
    return value


def test_installs_opaque_fc_task_id_compatibility():
    server = SimpleNamespace(validate_job_id=_uuid_only)
    jobs = SimpleNamespace(validate_job_id=_uuid_only)

    assert install_prompt_id_compat(server, jobs) is True
    assert server.validate_job_id("1-64f6d867-7302fc1ac6338b6fd2adb782") == "1-64f6d867-7302fc1ac6338b6fd2adb782"
    assert jobs.validate_job_id("my-task-001") == "my-task-001"

    with pytest.raises(ValueError):
        server.validate_job_id(123)
    with pytest.raises(ValueError):
        server.validate_job_id("")


def test_leaves_older_permissive_validator_unchanged():
    def permissive(value):
        return value

    server = SimpleNamespace(validate_job_id=permissive)

    assert install_prompt_id_compat(server) is False
    assert server.validate_job_id is permissive


def test_skips_versions_without_job_id_validator():
    assert install_prompt_id_compat(SimpleNamespace()) is False

