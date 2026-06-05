"""Idea2Video Pipeline — orchestrates the full idea-to-video generation flow.

Flow: idea → story → script (scenes) → shots → first/last frame images → videos → final
"""

import asyncio
import json
import logging
import os
import shutil

import yaml
from moviepy import VideoFileClip, concatenate_videoclips

from agents.screenwriter import Screenwriter
from tools.image_generator_agnes_api import ImageGeneratorAgnesAPI
from tools.video_generator_agnes_api import VideoGeneratorAgnesAPI

logger = logging.getLogger(__name__)


class Idea2VideoPipeline:
    """End-to-end pipeline: idea → story → scenes → shots → images → videos → final."""

    def __init__(
        self,
        api_key: str,
        chat_model: str = "agnes-2.0-flash",
        image_model: str = "agnes-image-2.1-flash",
        video_model: str = "agnes-video-v2.0",
        video_duration: int = 5,
        working_dir: str = ".working_dir/idea2video",
    ):
        self.api_key = api_key
        self.video_duration = video_duration
        self.working_dir = working_dir
        os.makedirs(working_dir, exist_ok=True)

        self.screenwriter = Screenwriter(api_key=api_key, model=chat_model)
        self.image_generator = ImageGeneratorAgnesAPI(api_key=api_key, model=image_model)
        self.video_generator = VideoGeneratorAgnesAPI(
            api_key=api_key, model=video_model, default_duration=video_duration
        )

    @classmethod
    def init_from_config(cls, config_path: str) -> "Idea2VideoPipeline":
        """Initialize pipeline from YAML config file."""
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        api_key = (
            config.get("api_key")
            or os.environ.get("AGNES_API_KEY", "")
        )
        chat_cfg = config.get("chat_model", {}).get("init_args", {})
        img_cfg = config.get("image_generator", {}).get("init_args", {})
        vid_cfg = config.get("video_generator", {}).get("init_args", {})

        # Merge api_key if not set in individual configs
        if not img_cfg.get("api_key"):
            img_cfg["api_key"] = api_key
        if not vid_cfg.get("api_key"):
            vid_cfg["api_key"] = api_key
        if not chat_cfg.get("api_key"):
            chat_cfg["api_key"] = api_key

        return cls(
            api_key=api_key,
            chat_model=chat_cfg.get("model", "agnes-2.0-flash"),
            image_model=img_cfg.get("model", "agnes-image-2.1-flash"),
            video_model=vid_cfg.get("model", "agnes-video-v2.0"),
            video_duration=vid_cfg.get("default_duration", 5),
            working_dir=config.get("working_dir", ".working_dir/idea2video"),
        )

    async def run(
        self,
        idea: str,
        user_requirement: str,
        style: str,
    ) -> str:
        """Run the full pipeline and return the path to the final video."""

        # ── Step 1: Develop Story ──
        story_path = os.path.join(self.working_dir, "story.txt")
        if os.path.exists(story_path):
            with open(story_path, "r") as f:
                story = f.read()
            logger.info("🚀 Story loaded from cache.")
        else:
            story = self.screenwriter.develop_story(idea, user_requirement, style)
            with open(story_path, "w") as f:
                f.write(story)
            logger.info(f"✅ Story saved to {story_path}")

        print(f"\n{'='*60}")
        print(f"📖 STORY:\n{story[:500]}...")
        print(f"{'='*60}\n")

        # ── Step 2: Write Script ──
        script_path = os.path.join(self.working_dir, "script.json")
        if os.path.exists(script_path):
            with open(script_path, "r") as f:
                scenes = json.load(f)
            logger.info(f"🚀 Script loaded from cache ({len(scenes)} scenes).")
        else:
            scenes = self.screenwriter.write_script(story, user_requirement, style)
            with open(script_path, "w") as f:
                json.dump(scenes, f, ensure_ascii=False, indent=2)
            logger.info(f"✅ Script saved ({len(scenes)} scenes)")

        print(f"🎬 SCENES: {len(scenes)}")
        for i, scene in enumerate(scenes):
            print(f"  Scene {i}: {scene[:100]}...")
        print()

        # ── Step 3: For each scene → shots → images → videos ──
        all_video_paths = []

        for scene_idx, scene_text in enumerate(scenes):
            print(f"\n{'─'*50}")
            print(f"🎥 Processing Scene {scene_idx}")
            print(f"{'─'*50}")

            scene_dir = os.path.join(self.working_dir, f"scene_{scene_idx}")
            os.makedirs(scene_dir, exist_ok=True)

            # Design shots
            shots_path = os.path.join(scene_dir, "shots.json")
            if os.path.exists(shots_path):
                with open(shots_path, "r") as f:
                    shots = json.load(f)
                logger.info(f"🚀 Shots loaded from cache ({len(shots)} shots).")
            else:
                shots = self.screenwriter.design_shots_for_scene(scene_text, style)
                with open(shots_path, "w") as f:
                    json.dump(shots, f, ensure_ascii=False, indent=2)
                logger.info(f"✅ {len(shots)} shots designed.")

            print(f"  Shots: {len(shots)}")
            for j, shot in enumerate(shots):
                print(f"    Shot {j}: {shot['ff_desc'][:80]}... → {shot['lf_desc'][:80]}...")

            # Generate first/last frame images + videos for each shot
            shot_video_paths = await self._process_shots(shots, scene_dir)

            # Concatenate shot videos into scene video
            if len(shot_video_paths) > 1:
                scene_video_path = os.path.join(scene_dir, "scene_video.mp4")
                if not os.path.exists(scene_video_path):
                    clips = [VideoFileClip(p) for p in shot_video_paths]
                    final = concatenate_videoclips(clips, method="compose")
                    final.write_videofile(scene_video_path, logger=None)
                    for c in clips:
                        c.close()
                    logger.info(f"✅ Scene {scene_idx} video: {scene_video_path}")
                all_video_paths.append(scene_video_path)
            elif shot_video_paths:
                all_video_paths.append(shot_video_paths[0])

        # ── Step 4: Concatenate all scene videos ──
        final_video_path = os.path.join(self.working_dir, "final_video.mp4")
        if os.path.exists(final_video_path):
            logger.info(f"🚀 Final video already exists: {final_video_path}")
        elif len(all_video_paths) > 1:
            logger.info(f"🎬 Concatenating {len(all_video_paths)} scene videos...")
            clips = [VideoFileClip(p) for p in all_video_paths]
            final = concatenate_videoclips(clips, method="compose")
            final.write_videofile(final_video_path, logger=None)
            for c in clips:
                c.close()
            logger.info(f"✅ Final video: {final_video_path}")
        elif all_video_paths:
            shutil.copy2(all_video_paths[0], final_video_path)
            logger.info(f"✅ Final video (single scene): {final_video_path}")
        else:
            raise RuntimeError("No videos were generated!")

        print(f"\n{'='*60}")
        print(f"🎉 FINAL VIDEO: {final_video_path}")
        print(f"{'='*60}\n")

        return final_video_path

    async def _process_shots(self, shots: list, scene_dir: str) -> list:
        """Process all shots in a scene: generate frames → videos."""
        video_paths = []

        for shot_idx, shot in enumerate(shots):
            shot_dir = os.path.join(scene_dir, f"shot_{shot_idx}")
            os.makedirs(shot_dir, exist_ok=True)

            ff_path = os.path.join(shot_dir, "first_frame.png")
            lf_path = os.path.join(shot_dir, "last_frame.png")
            video_path = os.path.join(shot_dir, "video.mp4")

            # Skip if video already exists
            if os.path.exists(video_path):
                logger.info(f"🚀 Shot {shot_idx} video exists, skipping.")
                video_paths.append(video_path)
                continue

            # Generate first frame
            if not os.path.exists(ff_path):
                print(f"  🖼️ Generating first frame for shot {shot_idx}...")
                ff_output = await self.image_generator.generate_single_image(
                    prompt=shot["ff_desc"],
                    size="1152x768",
                )
                ff_output.save(ff_path)
                logger.info(f"  ✅ First frame saved: {ff_path}")

            # Generate last frame (if variation is not "small")
            use_keyframes = shot.get("variation_type", "medium") != "small"
            if use_keyframes and not os.path.exists(lf_path):
                print(f"  🖼️ Generating last frame for shot {shot_idx}...")
                lf_output = await self.image_generator.generate_single_image(
                    prompt=shot["lf_desc"],
                    reference_image_paths=[ff_path],
                    size="1152x768",
                )
                lf_output.save(lf_path)
                logger.info(f"  ✅ Last frame saved: {lf_path}")

            # Generate video
            print(f"  🎬 Generating video for shot {shot_idx}...")

            if use_keyframes and os.path.exists(lf_path):
                # Keyframes mode: first + last frame → video
                ref_images = [ff_path, lf_path]
            else:
                # Single image mode: first frame → video
                ref_images = [ff_path]

            motion_desc = shot.get("motion_desc", "")
            video_output = await self.video_generator.generate_single_video(
                prompt=motion_desc,
                reference_image_paths=ref_images,
                duration=self.video_duration,
            )
            video_output.save(video_path)
            logger.info(f"  ✅ Video saved: {video_path}")
            video_paths.append(video_path)

        return video_paths

    async def __call__(self, idea: str, user_requirement: str, style: str) -> str:
        """Alias for run()."""
        return await self.run(idea=idea, user_requirement=user_requirement, style=style)
