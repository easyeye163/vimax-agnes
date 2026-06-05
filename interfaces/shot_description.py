from typing import List, Optional, Literal
from pydantic import BaseModel, Field


class ShotDescription(BaseModel):
    """A single shot in the storyboard, with first/last frame descriptions for video generation."""

    idx: int = Field(description="Shot index, starting from 0.")
    is_last: bool = Field(description="Whether this is the last shot.")

    visual_desc: str = Field(
        description="Vivid visual description of the shot including character actions and environment."
    )
    variation_type: Literal["large", "medium", "small"] = Field(
        description="Degree of change: large (scene change), medium (new element), small (minor movement)."
    )

    ff_desc: str = Field(description="First frame description — a static snapshot.")
    lf_desc: str = Field(description="Last frame description — a static snapshot.")
    motion_desc: str = Field(
        description="Motion description between first and last frame. Include any dialogue."
    )

    audio_desc: str = Field(
        default="",
        description="Audio description for the shot (sound effects, dialogue, music).",
    )
