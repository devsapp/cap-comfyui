"""Utility functions for FunArt APIs.

This module provides common utilities for downloading and converting media files.

Functions:
    download_url_to_bytes: Download content from URL, returns (bytes, size_mb)
    bytesio_to_image_tensor: Convert image bytes to ComfyUI IMAGE tensor
    bytesio_to_video_output: Convert video bytes to ComfyUI VIDEO output
    tensor_to_base64_string: Convert image tensor to base64 string
    tensor_to_data_uri: Convert image tensor to data URI
    audio_to_base64_string: Convert audio to base64 string
    audio_to_data_uri: Convert audio to data URI

DashScope helpers:
    get_dashscope_api_key: Get and validate DashScope API key
    setup_dashscope: Configure DashScope client
    initialize_dashscope: Initialize DashScope (get key + setup)

API call helpers:
    async_call_and_wait: Execute async API call and wait for completion
    sync_call: Execute synchronous API call
"""

from .api_call_helpers import async_call_and_wait, sync_call
from .conversions import (
    audio_to_base64_string,
    audio_to_data_uri,
    bytesio_to_image_tensor,
    bytesio_to_video_output,
    tensor_to_base64_string,
    tensor_to_data_uri,
    validate_audio_duration,
)
from .dashscope_helpers import (
    get_dashscope_api_key,
    initialize_dashscope,
    setup_dashscope,
)
from .download_helpers import download_url_to_bytes

__all__ = [
    # Download & conversion
    "download_url_to_bytes",
    "bytesio_to_image_tensor",
    "bytesio_to_video_output",
    "tensor_to_base64_string",
    "tensor_to_data_uri",
    "audio_to_base64_string",
    "audio_to_data_uri",
    "validate_audio_duration",
    # DashScope helpers
    "get_dashscope_api_key",
    "setup_dashscope",
    "initialize_dashscope",
    # API call helpers
    "async_call_and_wait",
    "sync_call",
]
