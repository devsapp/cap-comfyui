"""Compatibility for Function Compute task IDs on newer ComfyUI releases.

ComfyUI v0.27.0 only accepts canonical UUIDs when callers provide a
``prompt_id``. Function Compute task and request IDs are opaque strings, and
the Agent intentionally uses the same value end-to-end for queue, history,
status, and cancellation lookups. Keep that established contract while still
rejecting values that cannot safely be used as dictionary keys.
"""

from typing import Any


_PROBE_ID = "funart-fc-task-id"


def _validate_fc_task_id(value: Any) -> str:
    """Accept non-empty string IDs, matching the pre-v0.27 ComfyUI contract."""
    if not isinstance(value, str):
        raise ValueError(f"job id must be a string, got {type(value).__name__}")
    if not value:
        raise ValueError("job id must not be empty")
    return value


def install_prompt_id_compat(server_module=None, jobs_module=None) -> bool:
    """Relax UUID-only validation when the running ComfyUI requires it.

    ``server.py`` imports ``validate_job_id`` into its own module namespace, so
    both aliases are replaced. Older ComfyUI versions do not expose the
    validator (or already accept opaque IDs) and are left unchanged.

    Returns ``True`` when the compatibility validator was installed.
    """
    if server_module is None:
        try:
            import server as server_module
        except ImportError:
            return False

    validator = getattr(server_module, "validate_job_id", None)
    if not callable(validator):
        return False

    try:
        validator(_PROBE_ID)
    except (AttributeError, TypeError, ValueError):
        pass
    else:
        return False

    if jobs_module is None:
        try:
            from comfy_execution import jobs as jobs_module
        except ImportError:
            jobs_module = None

    server_module.validate_job_id = _validate_fc_task_id
    if jobs_module is not None:
        jobs_module.validate_job_id = _validate_fc_task_id

    print("[FunArt-APIs] Function Compute prompt_id compatibility enabled")
    return True

