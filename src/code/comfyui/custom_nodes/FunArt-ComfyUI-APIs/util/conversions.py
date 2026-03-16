"""
Conversion utilities for transforming between different data formats.

Based on ComfyUI's official implementation.
"""

import base64
import io
import math
from io import BytesIO
from typing import Optional

import numpy as np
import torch
from PIL import Image

try:
    from comfy_api.input_impl import VideoFromFile

    VIDEO_AVAILABLE = True
except ImportError:
    VIDEO_AVAILABLE = False
    VideoFromFile = None

try:
    from comfy.utils import common_upscale

    COMFY_UTILS_AVAILABLE = True
except ImportError:
    COMFY_UTILS_AVAILABLE = False
    common_upscale = None

try:
    import av

    AV_AVAILABLE = True
except ImportError:
    AV_AVAILABLE = False
    av = None


def bytesio_to_image_tensor(image_bytes: bytes, mode: str = "RGB") -> torch.Tensor:
    """Convert image bytes to a ComfyUI IMAGE tensor.

    Args:
        image_bytes: Raw image data as bytes
        mode: PIL image mode to convert to (default: "RGB")

    Returns:
        torch.Tensor: Image tensor with shape [1, H, W, C] in range [0, 1]

    Raises:
        PIL.UnidentifiedImageError: If the image data cannot be identified
        ValueError: If the specified mode is invalid
    """
    # Load image from bytes
    image = Image.open(io.BytesIO(image_bytes))

    # Convert to desired mode
    if image.mode != mode:
        image = image.convert(mode)

    # Convert to numpy array and normalize to [0, 1]
    image_array = np.array(image).astype(np.float32) / 255.0

    # Convert to tensor with batch dimension [1, H, W, C]
    return torch.from_numpy(image_array).unsqueeze(0)


def bytesio_to_video_output(video_bytes: bytes) -> Optional[object]:
    """Convert video bytes to a ComfyUI VIDEO output.

    Args:
        video_bytes: Raw video data as bytes

    Returns:
        VideoFromFile: ComfyUI VIDEO output object, or None if VIDEO not available

    Raises:
        ImportError: If comfy_api.input_impl.VideoFromFile is not available
    """
    if not VIDEO_AVAILABLE:
        raise ImportError("VideoFromFile is not available. " "Make sure comfy_api is installed and VideoFromFile is accessible.")

    # Create VideoFromFile directly from BytesIO
    # This avoids the need to write to disk
    return VideoFromFile(io.BytesIO(video_bytes))


# ============================================================================
# Image Tensor to Base64 Conversions
# ============================================================================


def downscale_image_tensor(image: torch.Tensor, total_pixels: int = 1536 * 1024) -> torch.Tensor:
    """Downscale input image tensor to roughly the specified total pixels.

    Args:
        image: Input image tensor [B, H, W, C]
        total_pixels: Maximum total pixels (default: 1536 * 1024)

    Returns:
        torch.Tensor: Downscaled image tensor (or original if already small enough)
    """
    if not COMFY_UTILS_AVAILABLE:
        # Fallback: no downscaling if comfy.utils not available
        return image

    samples = image.movedim(-1, 1)  # [B, H, W, C] -> [B, C, H, W]
    total = int(total_pixels)
    scale_by = math.sqrt(total / (samples.shape[3] * samples.shape[2]))

    if scale_by >= 1:
        return image  # No need to downscale

    width = round(samples.shape[3] * scale_by)
    height = round(samples.shape[2] * scale_by)

    s = common_upscale(samples, width, height, "lanczos", "disabled")
    s = s.movedim(1, -1)  # [B, C, H, W] -> [B, H, W, C]
    return s


def tensor_to_pil(image: torch.Tensor, total_pixels: int = 2048 * 2048) -> Image.Image:
    """Convert a torch.Tensor image [H, W, C] or [B, H, W, C] to a PIL Image.

    Args:
        image: Input torch.Tensor image
        total_pixels: Maximum total pixels for potential downscaling

    Returns:
        PIL.Image.Image: Converted PIL Image
    """
    if len(image.shape) > 3:
        image = image[0]  # Take first image if batched

    input_tensor = image.cpu()
    input_tensor = downscale_image_tensor(input_tensor.unsqueeze(0), total_pixels=total_pixels).squeeze()
    image_np = (input_tensor.numpy() * 255).astype(np.uint8)
    img = Image.fromarray(image_np)
    return img


def pil_to_bytesio(img: Image.Image, mime_type: str = "image/png") -> BytesIO:
    """Convert a PIL Image to a BytesIO object.

    Args:
        img: PIL Image
        mime_type: Target image MIME type (e.g., 'image/png', 'image/jpeg')

    Returns:
        BytesIO: Image data as BytesIO
    """
    if not mime_type:
        mime_type = "image/png"

    img_byte_arr = BytesIO()
    # Derive PIL format from MIME type (e.g., 'image/png' -> 'PNG')
    pil_format = mime_type.split("/")[-1].upper()
    if pil_format == "JPG":
        pil_format = "JPEG"
    img.save(img_byte_arr, format=pil_format)
    img_byte_arr.seek(0)
    return img_byte_arr


def tensor_to_base64_string(
    image_tensor: torch.Tensor,
    total_pixels: int = 2048 * 2048,
    mime_type: str = "image/png",
) -> str:
    """Convert [B, H, W, C] or [H, W, C] tensor to a base64 string.

    Args:
        image_tensor: Input torch.Tensor image
        total_pixels: Maximum total pixels for potential downscaling
        mime_type: Target image MIME type (e.g., 'image/png', 'image/jpeg', 'image/webp')

    Returns:
        str: Base64 encoded string of the image
    """
    pil_image = tensor_to_pil(image_tensor, total_pixels=total_pixels)
    img_byte_arr = pil_to_bytesio(pil_image, mime_type=mime_type)
    img_bytes = img_byte_arr.getvalue()
    base64_encoded_string = base64.b64encode(img_bytes).decode("utf-8")
    return base64_encoded_string


def tensor_to_data_uri(
    image_tensor: torch.Tensor,
    total_pixels: int = 2048 * 2048,
    mime_type: str = "image/png",
) -> str:
    """Convert a tensor image to a Data URI string.

    Args:
        image_tensor: Input torch.Tensor image
        total_pixels: Maximum total pixels for potential downscaling
        mime_type: Target image MIME type (e.g., 'image/png', 'image/jpeg', 'image/webp')

    Returns:
        str: Data URI string (e.g., 'data:image/png;base64,...')
    """
    base64_string = tensor_to_base64_string(image_tensor, total_pixels, mime_type)
    return f"data:{mime_type};base64,{base64_string}"


# ============================================================================
# Audio Tensor to Base64 Conversions
# ============================================================================


def audio_tensor_to_contiguous_ndarray(waveform: torch.Tensor) -> np.ndarray:
    """Prepare audio waveform for av library by converting to a contiguous numpy array.

    Args:
        waveform: Tensor of shape (1, channels, samples) derived from a Comfy `AUDIO` type

    Returns:
        np.ndarray: Contiguous numpy array of the audio waveform

    Raises:
        ValueError: If waveform shape is not (1, channels, samples)
    """
    if waveform.ndim != 3 or waveform.shape[0] != 1:
        raise ValueError(f"Expected waveform tensor shape (1, channels, samples), got {waveform.shape}")

    # Prepare for av: remove batch dim, move to CPU, make contiguous, convert to numpy array
    audio_data_np = waveform.squeeze(0).cpu().contiguous().numpy()
    if audio_data_np.dtype != np.float32:
        audio_data_np = audio_data_np.astype(np.float32)

    return audio_data_np


def audio_ndarray_to_bytesio(
    audio_data_np: np.ndarray,
    sample_rate: int,
    container_format: str = "mp4",
    codec_name: str = "aac",
) -> BytesIO:
    """Encode a numpy array of audio data into a BytesIO object.

    Args:
        audio_data_np: Audio data as numpy array [channels, samples]
        sample_rate: Audio sample rate (Hz)
        container_format: Container format (default: "mp4")
        codec_name: Audio codec name (default: "aac")

    Returns:
        BytesIO: Encoded audio data

    Raises:
        ImportError: If PyAV (av) is not available
    """
    if not AV_AVAILABLE:
        raise ImportError("PyAV (av) is not available. " "Install it with: pip install av")

    audio_bytes_io = BytesIO()
    with av.open(audio_bytes_io, mode="w", format=container_format) as output_container:
        audio_stream = output_container.add_stream(codec_name, rate=sample_rate)
        frame = av.AudioFrame.from_ndarray(
            audio_data_np,
            format="fltp",
            layout="stereo" if audio_data_np.shape[0] > 1 else "mono",
        )
        frame.sample_rate = sample_rate
        frame.pts = 0

        for packet in audio_stream.encode(frame):
            output_container.mux(packet)

        # Flush stream
        for packet in audio_stream.encode(None):
            output_container.mux(packet)

    audio_bytes_io.seek(0)
    return audio_bytes_io


def audio_to_base64_string(
    audio: dict,
    container_format: str = "mp4",
    codec_name: str = "aac",
) -> str:
    """Convert an audio input to a base64 string.

    Args:
        audio: ComfyUI AUDIO dict with 'waveform' and 'sample_rate'
        container_format: Container format (default: "mp4")
        codec_name: Audio codec name (default: "aac")

    Returns:
        str: Base64 encoded string of the audio
    """
    sample_rate: int = audio["sample_rate"]
    waveform: torch.Tensor = audio["waveform"]
    audio_data_np = audio_tensor_to_contiguous_ndarray(waveform)
    audio_bytes_io = audio_ndarray_to_bytesio(audio_data_np, sample_rate, container_format, codec_name)
    audio_bytes = audio_bytes_io.getvalue()
    return base64.b64encode(audio_bytes).decode("utf-8")


def audio_to_data_uri(
    audio: dict,
    container_format: str = "mp4",
    codec_name: str = "aac",
) -> str:
    """Convert an audio input to a Data URI string.

    Args:
        audio: ComfyUI AUDIO dict with 'waveform' and 'sample_rate'
        container_format: Container format (default: "mp4")
        codec_name: Audio codec name (default: "aac")

    Returns:
        str: Data URI string (e.g., 'data:audio/mp4;base64,...')
    """
    base64_string = audio_to_base64_string(audio, container_format, codec_name)
    # Determine MIME type from container format
    mime_type = f"audio/{container_format}"
    if container_format == "mp4":
        mime_type = "audio/mp4"
    elif container_format == "mp3":
        mime_type = "audio/mpeg"
    elif container_format == "wav":
        mime_type = "audio/wav"
    return f"data:{mime_type};base64,{base64_string}"


def validate_audio_duration(
    audio: dict,
    min_duration: Optional[float] = None,
    max_duration: Optional[float] = None,
) -> None:
    """Validate audio duration is within specified range.

    Args:
        audio: ComfyUI AUDIO dict with 'waveform' and 'sample_rate'
        min_duration: Minimum duration in seconds (optional)
        max_duration: Maximum duration in seconds (optional)

    Raises:
        ValueError: If audio duration is out of range
    """
    sample_rate = int(audio["sample_rate"])
    waveform = audio["waveform"]
    num_samples = int(waveform.shape[-1])
    duration = num_samples / sample_rate
    eps = 1.0 / sample_rate  # One sample period tolerance

    if min_duration is not None and duration + eps < min_duration:
        raise ValueError(
            f"Audio duration must be at least {min_duration}s, got {duration + eps:.2f}s. "
            f"Please provide audio between {min_duration}s and {max_duration or 'any'}s."
        )
    if max_duration is not None and duration - eps > max_duration:
        raise ValueError(
            f"Audio duration must be at most {max_duration}s, got {duration - eps:.2f}s. "
            f"Please provide audio between {min_duration or 'any'}s and {max_duration}s."
        )
