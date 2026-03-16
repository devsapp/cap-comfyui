"""
Download helpers for fetching content from URLs.

Based on ComfyUI's official implementation with simplifications for synchronous usage.
"""

import time
from typing import Tuple

import requests


def download_url_to_bytes(
    url: str,
    timeout: int = 60,
    max_retries: int = 3,
    retry_delay: float = 1.0,
) -> Tuple[bytes, float]:
    """Download content from a URL and return bytes with file size.

    Args:
        url: The URL to download from
        timeout: Request timeout in seconds (default: 60)
        max_retries: Maximum number of retry attempts (default: 3)
        retry_delay: Initial delay between retries in seconds (default: 1.0)

    Returns:
        Tuple[bytes, float]: (downloaded content, file size in MB)

    Raises:
        requests.RequestException: If download fails after all retries
    """
    attempt = 0
    delay = retry_delay

    while True:
        attempt += 1
        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()

            content = response.content
            content_size_mb = len(content) / (1024 * 1024)

            return content, content_size_mb

        except requests.RequestException as e:
            if attempt >= max_retries:
                print(f"❌ Download failed after {max_retries} attempts: {e}")
                raise

            print(f"⚠️  Download failed (attempt {attempt}/{max_retries}): {e}")
            print(f"   Retrying in {delay:.1f}s...")
            time.sleep(delay)

            # Exponential backoff
            delay *= 2.0
