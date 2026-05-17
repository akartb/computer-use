"""
MSS-based screen capture plugin for Computer Use Plugin.

Provides cross-platform screenshot capture using the mss library.
Supports multi-monitor, region selection, DPI awareness, and quality settings.
"""

from __future__ import annotations

import base64
import io
import logging
import time
from typing import Any

from PIL import Image

from src.sdk.base import BasePlugin
from src.sdk.hooks import hookimpl
from src.sdk.models import DisplayInfo, Region, Screenshot

logger = logging.getLogger(__name__)


class MssScreenPlugin(BasePlugin):
    """
    Screen capture plugin using the mss library.

    Supports multi-monitor capture, region selection, configurable quality,
    DPI-aware coordinates, and resolution downscaling for API efficiency.

    Configuration:
        capture_method: Capture backend ('mss' or 'pillow'). Default: 'mss'.
        monitor: Default monitor index. Default: 0.
        dpi_aware: Whether to handle DPI scaling. Default: True.
        quality: JPEG/PNG quality (1-100). Default: 85.
        format: Image format ('png' or 'jpeg'). Default: 'png'.
        max_width: Maximum width for downscaling (0 = no limit). Default: 0.
        max_height: Maximum height for downscaling (0 = no limit). Default: 0.
    """

    def __init__(self) -> None:
        super().__init__()
        self._capture_method: str = "mss"
        self._default_monitor: int = 0
        self._dpi_aware: bool = True
        self._quality: int = 85
        self._image_format: str = "png"
        self._max_width: int = 0
        self._max_height: int = 0

    @property
    def name(self) -> str:
        return "screen-mss"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def description(self) -> str:
        return "Cross-platform screen capture using mss library"

    async def initialize(self, config: dict[str, Any]) -> None:
        """
        Initialize the screen capture plugin.

        Args:
            config: Plugin configuration dictionary.
        """
        self._config = config
        self._capture_method = config.get("capture_method", "mss")
        self._default_monitor = config.get("monitor", 0)
        self._dpi_aware = config.get("dpi_aware", True)
        self._quality = config.get("quality", 85)
        self._image_format = config.get("format", "png")
        self._max_width = config.get("max_width", 0)
        self._max_height = config.get("max_height", 0)
        self._initialized = True
        logger.info(
            "MssScreenPlugin initialized: method=%s, monitor=%d, format=%s, quality=%d",
            self._capture_method, self._default_monitor, self._image_format, self._quality,
        )

    async def capture(self, monitor: int | None = None, region: Region | None = None) -> Screenshot:
        """
        Capture a screenshot of the specified screen region.

        Args:
            monitor: Monitor index (0 = primary). Uses default if None.
            region: Optional region to capture instead of full screen.

        Returns:
            Screenshot object containing base64-encoded image data and metadata.
        """
        import mss

        monitor_idx = monitor if monitor is not None else self._default_monitor
        timestamp = time.time()

        with mss.mss() as sct:
            monitors = sct.monitors
            if monitor_idx >= len(monitors):
                monitor_idx = 0

            if region is not None:
                monitor_dict = {
                    "left": region.x,
                    "top": region.y,
                    "width": region.width,
                    "height": region.height,
                }
            else:
                monitor_dict = monitors[monitor_idx]

            raw = sct.grab(monitor_dict)
            img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

            original_width, original_height = img.size

            if self._max_width > 0 or self._max_height > 0:
                img = self._downscale(img)

            width, height = img.size
            encoded = self._encode_image(img)

        return Screenshot(
            data=encoded,
            width=width,
            height=height,
            monitor=monitor_idx,
            region=region,
            timestamp=timestamp,
        )

    async def get_display_info(self) -> list[DisplayInfo]:
        """
        Get information about all connected displays.

        Returns:
            List of DisplayInfo objects with resolution, position, etc.
        """
        import mss

        displays: list[DisplayInfo] = []
        with mss.mss() as sct:
            for i, mon in enumerate(sct.monitors[1:], start=0):
                displays.append(DisplayInfo(
                    index=i,
                    width=mon["width"],
                    height=mon["height"],
                    x=mon["left"],
                    y=mon["top"],
                    is_primary=(i == 0),
                ))
        return displays

    def _downscale(self, img: Image.Image) -> Image.Image:
        """
        Downscale an image to fit within max dimensions while preserving aspect ratio.

        Args:
            img: PIL Image to potentially downscale.

        Returns:
            Resized PIL Image, or the original if no downscaling needed.
        """
        w, h = img.size
        max_w = self._max_width if self._max_width > 0 else w
        max_h = self._max_height if self._max_height > 0 else h

        if w <= max_w and h <= max_h:
            return img

        ratio = min(max_w / w, max_h / h)
        new_w = int(w * ratio)
        new_h = int(h * ratio)
        return img.resize((new_w, new_h), Image.LANCZOS)

    def _encode_image(self, img: Image.Image) -> str:
        """
        Encode a PIL Image to base64 string.

        Args:
            img: PIL Image to encode.

        Returns:
            Base64-encoded string of the image data.
        """
        buffer = io.BytesIO()
        fmt = "JPEG" if self._image_format == "jpeg" else "PNG"
        kwargs: dict[str, Any] = {"format": fmt}
        if fmt == "JPEG":
            kwargs["quality"] = self._quality
        img.save(buffer, **kwargs)
        return base64.b64encode(buffer.getvalue()).decode("utf-8")

    @hookimpl
    def on_capture_screen(self, monitor: int = 0, region: dict | None = None) -> dict:
        """
        Hook implementation for screen capture.

        Args:
            monitor: Monitor index.
            region: Optional region dict.

        Returns:
            Dict with screenshot data and metadata.
        """
        import asyncio

        region_obj = Region(**region) if region else None

        loop = asyncio.get_event_loop()
        screenshot = loop.run_until_complete(self.capture(monitor, region_obj))

        return {
            "data": screenshot.data,
            "width": screenshot.width,
            "height": screenshot.height,
            "monitor": screenshot.monitor,
            "timestamp": screenshot.timestamp,
        }
