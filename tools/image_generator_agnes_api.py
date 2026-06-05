"""Agnes AI Image Generator — implements ImageGenerator protocol."""

import logging
from typing import List, Optional
import requests
from interfaces.image_output import ImageOutput

logger = logging.getLogger(__name__)

BASE_URL = "https://apihub.agnes-ai.com/v1"


class ImageGeneratorAgnesAPI:
    """Generate images using Agnes AI agnes-image-2.1-flash."""

    def __init__(self, api_key: str, model: str = "agnes-image-2.1-flash"):
        self.api_key = api_key
        self.model = model
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    async def generate_single_image(
        self,
        prompt: str,
        reference_image_paths: List[str] = [],
        size: Optional[str] = None,
        **kwargs,
    ) -> ImageOutput:
        """
        Generate an image.

        - No reference images → text-to-image
        - With reference images → image-to-image via extra_body
        """
        payload: dict = {
            "model": self.model,
            "prompt": prompt,
            "size": size or "1024x1024",
        }

        if reference_image_paths:
            # Image-to-image mode
            extra_body: dict = {"response_format": "url"}
            if len(reference_image_paths) == 1:
                extra_body["image"] = reference_image_paths[0]
            else:
                extra_body["image"] = reference_image_paths
            payload["extra_body"] = extra_body

        logger.info(f"[Agnes Image] Generating: {prompt[:80]}...")
        resp = requests.post(
            f"{BASE_URL}/images/generations",
            headers=self.headers,
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        result = resp.json()

        if "error" in result:
            err = result["error"]
            raise RuntimeError(f"Agnes image error: {err.get('message', err)}")

        data_list = result.get("data", [])
        if not data_list:
            raise RuntimeError("Agnes image: no data returned")

        url = data_list[0].get("url", "")
        if not url:
            raise RuntimeError("Agnes image: no URL in response")

        logger.info(f"[Agnes Image] Done: {url[:80]}...")
        return ImageOutput(fmt="url", ext="png", data=url)
