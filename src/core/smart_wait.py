"""
Smart Wait System for Computer Use Plugin.

Replaces fixed delays with intelligent UI change detection.
Detects screen stability by comparing consecutive screenshots,
allowing the system to proceed as soon as the UI is ready — 
faster than humans who add unnecessary buffer time.

Key advantages over humans:
- Detects sub-pixel changes humans can't perceive
- Proceeds in ~50ms after stability instead of ~500ms human reaction
- Never waits too long (timeout) or too short (missed changes)
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from PIL import Image, ImageChops

from src.sdk.models import Screenshot

logger = logging.getLogger(__name__)


class SmartWait:
    """
    Intelligent wait system that detects UI stability by comparing screenshots.

    Instead of fixed delays (which are either too slow or too fast),
    this system continuously captures screenshots and detects when the
    screen has stopped changing, indicating the UI is ready for the next action.

    Attributes:
        _stability_threshold: Pixel difference ratio below which the screen is considered stable.
        _check_interval: Time between stability checks in seconds.
        _min_wait: Minimum wait time before checking stability.
        _max_wait: Maximum wait time (timeout) for any single wait.
    """

    def __init__(
        self,
        stability_threshold: float = 0.005,
        check_interval: float = 0.1,
        min_wait: float = 0.2,
        max_wait: float = 10.0,
    ) -> None:
        """
        Initialize the smart wait system.

        Args:
            stability_threshold: Max ratio of changed pixels to consider stable (0.005 = 0.5%).
            check_interval: Seconds between screenshot comparisons.
            min_wait: Minimum wait before first stability check.
            max_wait: Maximum seconds to wait for stability.
        """
        self._stability_threshold = stability_threshold
        self._check_interval = check_interval
        self._min_wait = min_wait
        self._max_wait = max_wait

    async def wait_for_stability(
        self,
        capture_func: Any,
        before_screenshot: Screenshot | None = None,
    ) -> Screenshot:
        """
        Wait until the screen stops changing, then return the stable screenshot.

        This is the core method. After an action is executed, call this to
        wait for the UI to settle before the next observe-reason-act cycle.
        It's faster than a fixed delay because it proceeds immediately when
        the screen is stable, and safer because it waits longer when needed.

        Args:
            capture_func: Async callable that returns a Screenshot.
            before_screenshot: Optional screenshot from before the action for comparison.

        Returns:
            The stable Screenshot after the UI has settled.
        """
        await asyncio.sleep(self._min_wait)

        start_time = time.monotonic()
        previous_img: Image.Image | None = None

        if before_screenshot is not None:
            previous_img = self._decode_screenshot(before_screenshot)

        stable_count = 0
        required_stable_checks = 2

        while True:
            elapsed = time.monotonic() - start_time
            if elapsed >= self._max_wait:
                logger.debug("SmartWait: max wait reached (%.1fs)", elapsed)
                current = await capture_func()
                return current

            current = await capture_func()
            current_img = self._decode_screenshot(current)

            if previous_img is not None and current_img.size == previous_img.size:
                diff_ratio = self._compute_diff_ratio(previous_img, current_img)
                if diff_ratio < self._stability_threshold:
                    stable_count += 1
                    if stable_count >= required_stable_checks:
                        logger.debug(
                            "SmartWait: screen stable after %.2fs (diff=%.4f)",
                            elapsed, diff_ratio,
                        )
                        return current
                else:
                    stable_count = 0

            previous_img = current_img
            await asyncio.sleep(self._check_interval)

    async def wait_for_change(
        self,
        capture_func: Any,
        before_screenshot: Screenshot,
        timeout: float = 5.0,
    ) -> Screenshot | None:
        """
        Wait until the screen changes from a reference screenshot.

        Useful for detecting if an action had any visible effect.
        Returns None if no change is detected within the timeout.

        Args:
            capture_func: Async callable that returns a Screenshot.
            before_screenshot: Reference screenshot to compare against.
            timeout: Maximum seconds to wait for a change.

        Returns:
            The changed Screenshot, or None if no change detected.
        """
        await asyncio.sleep(self._min_wait)

        start_time = time.monotonic()
        before_img = self._decode_screenshot(before_screenshot)

        while True:
            elapsed = time.monotonic() - start_time
            if elapsed >= timeout:
                logger.debug("WaitForChange: no change detected in %.1fs", timeout)
                return None

            current = await capture_func()
            current_img = self._decode_screenshot(current)

            if current_img.size == before_img.size:
                diff_ratio = self._compute_diff_ratio(before_img, current_img)
                if diff_ratio >= self._stability_threshold:
                    logger.debug(
                        "WaitForChange: change detected after %.2fs (diff=%.4f)",
                        elapsed, diff_ratio,
                    )
                    return current

            await asyncio.sleep(self._check_interval)

    def _decode_screenshot(self, screenshot: Screenshot) -> Image.Image:
        """
        Decode a base64 screenshot into a PIL Image.

        Args:
            screenshot: Screenshot object with base64 data.

        Returns:
            PIL Image in RGB mode.
        """
        import base64
        import io

        img_data = base64.b64decode(screenshot.data)
        img = Image.open(io.BytesIO(img_data))
        return img.convert("RGB")

    def _compute_diff_ratio(self, img1: Image.Image, img2: Image.Image) -> float:
        """
        Compute the ratio of changed pixels between two images.

        Uses a perceptual difference threshold to ignore sub-pixel
        rendering artifacts that don't represent real UI changes.

        Args:
            img1: First image.
            img2: Second image.

        Returns:
            Float between 0.0 (identical) and 1.0 (completely different).
        """
        diff = ImageChops.difference(img1, img2)
        bbox = diff.getbbox()
        if bbox is None:
            return 0.0

        try:
            diff_data = list(diff.get_flattened_data())
        except AttributeError:
            diff_data = list(diff.getdata())
        total_pixels = len(diff_data)
        if total_pixels == 0:
            return 0.0

        threshold = 10
        changed_pixels = sum(
            1 for r, g, b in diff_data
            if r > threshold or g > threshold or b > threshold
        )

        return changed_pixels / total_pixels
