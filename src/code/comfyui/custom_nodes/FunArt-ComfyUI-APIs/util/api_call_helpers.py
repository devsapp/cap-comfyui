"""
DashScope API call helpers for async and sync operations.

This module provides generic methods for DashScope API interactions,
allowing nodes to focus on parameter construction and result parsing.
"""

from http import HTTPStatus
from typing import Any, Callable


def async_call_and_wait(
    async_call_func: Callable,
    wait_func: Callable,
    params: dict,
    api_key: str,
    task_name: str = "Task",
) -> Any:
    """Execute async API call and wait for completion.

    Generic async workflow:
    1. Call async API to submit task
    2. Get task_id from response
    3. Poll with wait() until completion
    4. Validate response status
    5. Return final result

    Args:
        async_call_func: Async call function (e.g., VideoSynthesis.async_call)
        wait_func: Wait function (e.g., VideoSynthesis.wait)
        params: Parameters for async_call
        api_key: API key for wait() call
        task_name: Task name for logging (default: "Task")

    Returns:
        Final response object from wait()

    Raises:
        RuntimeError: If async call or task execution fails

    Example:
        ```python
        # In node:
        params = {"model": "wan2.6-turbo-v1", "prompt": prompt, ...}
        result = async_call_and_wait(
            async_call_func=VideoSynthesis.async_call,
            wait_func=VideoSynthesis.wait,
            params=params,
            api_key=effective_api_key,
            task_name="Video Generation"
        )
        # Parse result...
        video_url = result.output.video_url
        ```
    """
    # Step 1: Submit async task
    rsp = async_call_func(**params)

    # Validate async call response
    if rsp.status_code != HTTPStatus.OK:
        raise RuntimeError(f"❌ {task_name} submission failed: {rsp.code} - {rsp.message}")

    # Extract task_id
    task_id = rsp.output.task_id if rsp.output else None
    if not task_id:
        raise RuntimeError(f"❌ {task_name} submission failed: No task_id returned")

    print(f"✓ Task submitted (ID: {task_id})")

    # Step 2: Wait for completion
    print(f"Waiting for {task_name} to complete...")
    result = wait_func(task=rsp, api_key=api_key)

    # Validate final response
    if result.status_code != HTTPStatus.OK:
        raise RuntimeError(f"❌ {task_name} failed: {result.code} - {result.message}")

    print(f"✓ {task_name} completed")
    return result


def sync_call(
    call_func: Callable,
    params: dict,
    task_name: str = "Task",
) -> Any:
    """Execute synchronous API call.

    Generic sync workflow:
    1. Call API directly
    2. Validate response status
    3. Return result

    Args:
        call_func: Sync call function (e.g., MultiModalConversation.call)
        params: Parameters for call
        task_name: Task name for logging (default: "Task")

    Returns:
        Response object from API call

    Raises:
        RuntimeError: If API call fails

    Example:
        ```python
        # In node:
        params = {"model": "wan2.6-turbo-v1", "messages": messages, ...}
        response = sync_call(
            call_func=MultiModalConversation.call,
            params=params,
            task_name="Image Generation"
        )
        # Parse response...
        image_urls = [item.image for item in response.output.choices[0].message.content]
        ```
    """
    # Execute sync call
    print(f"Calling {task_name}...")
    response = call_func(**params)

    # Validate response
    if response.status_code != HTTPStatus.OK:
        raise RuntimeError(f"❌ {task_name} failed: {response.code} - {response.message}")

    print(f"✓ {task_name} completed")
    return response
