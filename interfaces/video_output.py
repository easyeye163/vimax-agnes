import requests
from typing import Literal, Union
from utils.image import download_image
from utils.video import download_video


class ImageOutput:
    """Container for generated image — supports URL or base64."""

    def __init__(self, fmt: Literal["url", "b64"], ext: str, data: str):
        self.fmt = fmt
        self.ext = ext
        self.data = data

    def save(self, path: str) -> None:
        if self.fmt == "url":
            download_image(self.data, path)
        else:
            import base64
            raw = self.data.split(",")[1] if "," in self.data else self.data
            with open(path, "wb") as f:
                f.write(base64.b64decode(raw))


class VideoOutput:
    """Container for generated video — supports URL or bytes."""

    def __init__(self, fmt: Literal["url", "bytes"], ext: str, data: Union[str, bytes]):
        self.fmt = fmt
        self.ext = ext
        self.data = data

    def save(self, path: str) -> None:
        if self.fmt == "url":
            download_video(self.data, path)
        else:
            with open(path, "wb") as f:
                f.write(self.data if isinstance(self.data, bytes) else self.data.encode())
