#!/usr/bin/env python3
"""ViMax-Agnes: Transform ideas into complete videos using Agnes AI.

Usage:
    # Set API key
    export AGNES_API_KEY="your-agnes-api-key"

    # Or edit configs/idea2video.yaml

    # Run
    python main_idea2video.py
"""

import asyncio
import logging
import os
import sys

from pipelines.idea2video_pipeline import Idea2VideoPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

# ═══════════════════════════════════════════════════════════════
# SET YOUR OWN IDEA, USER REQUIREMENT, AND STYLE HERE
# ═══════════════════════════════════════════════════════════════

idea = \
"""
唱歌跳舞：一位美丽的女孩站在绚丽的舞台上，先是深情演唱，然后切换为活力四射的舞蹈表演，最后以一个惊艳的定格动作结束
"""

user_requirement = \
"""
3个场景，每个场景10秒，电影质感，MV风格，竖屏拍摄
"""

style = "电影质感MV风格"

# Optional: provide a reference image (local path or URL).
# If set, this image will be used as the first-frame reference for
# ALL scene videos (ti2vid mode), keeping character/scene consistency.
# When empty, the pipeline auto-generates a character reference image.
reference_image = "/home/z/my-project/upload/weixin-image.jpg"

# Optional: enable scene chaining mode for visual continuity.
# When True, each scene's first frame is derived from the previous
# scene's last frame via image-to-image generation, creating smooth
# transitions between scenes. Each scene should be ~10 seconds.
# This mode is sequential (not parallel), so total time = N scenes × (video + img2img).
scene_chaining = True

# Video dimensions (portrait 768x1152 for vertical reference images)
video_width = 768
video_height = 1152

# ═══════════════════════════════════════════════════════════════


def resolve_api_key() -> str:
    """Resolve API key from config or environment."""
    key = os.environ.get("AGNES_API_KEY", "")
    if not key:
        config_path = os.path.join(os.path.dirname(__file__), "configs", "idea2video.yaml")
        if os.path.exists(config_path):
            import yaml
            with open(config_path) as f:
                config = yaml.safe_load(f)
            key = config.get("api_key", "")
            if key.startswith("${") and key.endswith("}"):
                env_name = key[2:-1]
                key = os.environ.get(env_name, "")
    if not key:
        print("Error: AGNES_API_KEY not set.")
        print("   Please set it via:")
        print("     export AGNES_API_KEY='your-api-key'")
        print("   Or edit configs/idea2video.yaml")
        sys.exit(1)
    return key


async def main():
    api_key = resolve_api_key()

    pipeline = Idea2VideoPipeline.init_from_config(
        config_path=os.path.join(os.path.dirname(__file__), "configs", "idea2video.yaml")
    )
    # Override api_key from environment (takes priority)
    if os.environ.get("AGNES_API_KEY"):
        pipeline.api_key = api_key
        pipeline.screenwriter.api_key = api_key
        pipeline.image_generator.api_key = api_key
        pipeline.video_generator.api_key = api_key
        for h in [pipeline.screenwriter.headers, pipeline.image_generator.headers, pipeline.video_generator.headers]:
            h["Authorization"] = f"Bearer {api_key}"

    final_path = await pipeline(
        idea=idea,
        user_requirement=user_requirement,
        style=style,
        reference_image=reference_image,
        scene_chaining=scene_chaining,
        video_width=video_width,
        video_height=video_height,
    )
    print(f"\nDone! Final video: {final_path}")


if __name__ == "__main__":
    asyncio.run(main())
