"""Render backend initialization from YAML config."""

import yaml
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class RenderBackend:
    """Holds image and video generator instances."""

    def __init__(self, image_generator, video_generator):
        self.image_generator = image_generator
        self.video_generator = video_generator

    @classmethod
    def from_config(cls, config: dict):
        image_cfg = config.get("image_generator", {})
        video_cfg = config.get("video_generator", {})

        # Image generator
        img_class_path = image_cfg.get("class_path", "")
        img_args = image_cfg.get("init_args", {})

        if "AgnesAPI" in img_class_path or img_args.get("api_key"):
            from tools.image_generator_agnes_api import ImageGeneratorAgnesAPI
            image_generator = ImageGeneratorAgnesAPI(
                api_key=img_args.get("api_key", ""),
                model=img_args.get("model", "agnes-image-2.1-flash"),
            )
        else:
            raise ValueError(f"Unknown image generator: {img_class_path}")

        # Video generator
        vid_class_path = video_cfg.get("class_path", "")
        vid_args = video_cfg.get("init_args", {})

        if "AgnesAPI" in vid_class_path or vid_args.get("api_key"):
            from tools.video_generator_agnes_api import VideoGeneratorAgnesAPI
            video_generator = VideoGeneratorAgnesAPI(
                api_key=vid_args.get("api_key", ""),
                model=vid_args.get("model", "agnes-video-v2.0"),
                default_duration=vid_args.get("default_duration", 5),
            )
        else:
            raise ValueError(f"Unknown video generator: {vid_class_path}")

        return cls(image_generator=image_generator, video_generator=video_generator)
