"""Structural typing contracts for rendering backends."""

from typing import List, Protocol, runtime_checkable
from interfaces.image_output import ImageOutput
from interfaces.video_output import VideoOutput


@runtime_checkable
class ImageGenerator(Protocol):
    async def generate_single_image(self, prompt: str, reference_image_paths: List[str] = [], **kwargs) -> ImageOutput: ...


@runtime_checkable
class VideoGenerator(Protocol):
    async def generate_single_video(self, prompt: str, reference_image_paths: List[str] = [], **kwargs) -> VideoOutput: ...
