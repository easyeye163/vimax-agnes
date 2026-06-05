"""Agnes AI Video Generator — implements VideoGenerator protocol.

Supports three modes:
  - Text-to-video (t2v): prompt only, no reference images
  - Image-to-video (ti2vid): 1 reference image as first frame
  - Keyframes video: 2+ reference images (first + last frame)
"""

import asyncio
import base64
import logging
import mimetypes
import os
import time
from typing import List, Optional
import requests
from interfaces.video_output import VideoOutput

logger = logging.getLogger(__name__)

BASE_URL = "https://apihub.agnes-ai.com/v1"

# Duration presets: (num_frames, frame_rate) — max 441 frames, must be 8n+1
DURATION_PRESETS = {
    5: (121, 24),
    10: (241, 24),
    15: (361, 24),
    18: (441, 24),
    20: (441, 22),
}


class VideoGeneratorAgnesAPI:
    """Generate videos using Agnes AI agnes-video-v2.0."""

    def __init__(
        self,
        api_key: str,
        model: str = "agnes-video-v2.0",
        default_duration: int = 5,
    ):
        self.api_key = api_key
        self.model = model
        self.default_duration = default_duration
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _path_to_b64(self, path: str) -> str:
        """Convert a local image file path to base64 data URI."""
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        mime = mimetypes.guess_type(path)[0] or "image/png"
        return f"data:{mime};base64,{b64}"

    def _resolve_image_ref(self, ref: str) -> str:
        """Resolve an image reference: return URL as-is, convert local path to b64."""
        if ref.startswith(("http://", "https://", "data:")):
            return ref
        if os.path.exists(ref):
            logger.info(f"[Agnes Video] Converting local image to b64: {ref}")
            return self._path_to_b64(ref)
        return ref

    def _get_frame_config(self, duration: Optional[int] = None) -> tuple:
        d = duration or self.default_duration
        if d in DURATION_PRESETS:
            return DURATION_PRESETS[d]
        # Find the best fit: largest num_frames <= 441 that satisfies 8n+1
        best = None
        for nf in range(9, 442, 8):
            fr = round(nf / d)
            if 1 <= fr <= 60:
                best = (nf, fr)
        return best or DURATION_PRESETS[5]

    async def _poll_task(self, task_id: str, timeout: int = 600, interval: int = 15) -> dict:
        """Poll video task until completed or failed."""
        deadline = time.time() + timeout
        last_status = ""
        while time.time() < deadline:
            try:
                resp = requests.get(
                    f"{BASE_URL}/videos/{task_id}",
                    headers=self.headers,
                    timeout=15,
                )
                resp.raise_for_status()
                result = resp.json()
                status = result.get("status", "")
                progress = result.get("progress", 0)

                if status != last_status:
                    logger.info(f"[Agnes Video] Task {task_id[:16]}... status={status} progress={progress}%")
                    last_status = status

                if status in ("completed", "COMPLETED"):
                    return result

                if status in ("failed", "FAILED"):
                    err = result.get("error") or "unknown error"
                    raise RuntimeError(f"Video generation failed: {err}")
            except requests.exceptions.RequestException as e:
                logger.warning(f"[Agnes Video] Poll error: {e}")

            await asyncio.sleep(interval)

        raise TimeoutError(f"Video task {task_id} timed out after {timeout}s")

    async def generate_single_video(
        self,
        prompt: str,
        reference_image_paths: List[str] = [],
        duration: Optional[int] = None,
        width: int = 1152,
        height: int = 768,
        seed: Optional[int] = None,
        negative_prompt: Optional[str] = None,
        **kwargs,
    ) -> VideoOutput:
        """
        Generate a video.

        - 0 reference images → text-to-video
        - 1 reference image → image-to-video (ti2vid mode)
        - 2+ reference images → keyframes video
        """
        num_frames, frame_rate = self._get_frame_config(duration)

        payload: dict = {
            "model": self.model,
            "prompt": prompt,
            "width": width,
            "height": height,
            "num_frames": num_frames,
            "frame_rate": frame_rate,
        }

        if seed is not None:
            payload["seed"] = seed
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt

        # Resolve local paths to b64 data URIs
        resolved_refs = [self._resolve_image_ref(p) for p in reference_image_paths]
        n_refs = len(resolved_refs)

        if n_refs == 0:
            # Text-to-video
            mode_desc = "text-to-video"
        elif n_refs == 1:
            # Image-to-video: single image as first frame (top-level params)
            payload["image"] = resolved_refs[0]
            payload["mode"] = "ti2vid"
            mode_desc = "image-to-video"
        else:
            # Keyframes: multiple images via extra_body
            payload["extra_body"] = {
                "image": resolved_refs,
                "mode": "keyframes",
            }
            mode_desc = f"keyframes ({n_refs} frames)"

        logger.info(f"[Agnes Video] {mode_desc}: {prompt[:80]}...")

        try:
            resp = requests.post(
                f"{BASE_URL}/videos",
                headers=self.headers,
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            error_detail = ""
            try:
                error_detail = resp.text[:500]
            except Exception:
                pass
            logger.error(f"[Agnes Video] HTTP {resp.status_code}: {error_detail}")
            raise

        result = resp.json()

        if "error" in result:
            raise RuntimeError(f"Agnes video error: {result['error']}")

        task_id = result.get("task_id") or result.get("id")
        if not task_id:
            raise RuntimeError(f"Agnes video: no task_id returned: {result}")

        logger.info(f"[Agnes Video] Task submitted: {task_id[:20]}... waiting...")

        # Poll until done
        final = await self._poll_task(task_id)

        # Extract video URL from response
        video_url = (
            final.get("remixed_from_video_id")
            or final.get("video_url")
            or final.get("url")
        )
        if not video_url:
            # Try data field
            data = final.get("data", {})
            if isinstance(data, dict):
                video_url = data.get("video_url") or data.get("url")
            if not video_url:
                raise RuntimeError(f"Agnes video: no URL in completed task: {final}")

        logger.info(f"[Agnes Video] Done: {video_url[:80]}...")
        return VideoOutput(fmt="url", ext="mp4", data=video_url)
