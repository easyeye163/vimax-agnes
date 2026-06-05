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
一个机器人在温泉旁边徘徊，不确定能不能游泳
"""

user_requirement = \
"""
不超过5个场景
"""

style = "写实风格"

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
    )
    print(f"\nDone! Final video: {final_path}")


if __name__ == "__main__":
    asyncio.run(main())
