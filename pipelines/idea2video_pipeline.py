"""Idea2Video Pipeline — orchestrates the full idea-to-video generation flow.

Flow:
  idea -> story -> character reference image -> script (scenes) -> videos (ti2vid) -> final
"""

import asyncio
import json
import logging
import os
import shutil
import subprocess

import yaml
from moviepy import VideoFileClip, concatenate_videoclips

from agents.screenwriter import Screenwriter
from tools.image_generator_agnes_api import ImageGeneratorAgnesAPI
from tools.video_generator_agnes_api import VideoGeneratorAgnesAPI

logger = logging.getLogger(__name__)


class Idea2VideoPipeline:
    """End-to-end pipeline: idea -> story -> character ref -> scenes -> videos -> final."""

    def __init__(
        self,
        api_key: str,
        chat_model: str = "agnes-2.0-flash",
        image_model: str = "agnes-image-2.1-flash",
        video_model: str = "agnes-video-v2.0",
        video_duration: int = 5,
        video_width: int = 1152,
        video_height: int = 768,
        working_dir: str = ".working_dir/idea2video",
    ):
        self.api_key = api_key
        self.video_duration = video_duration
        self.video_width = video_width
        self.video_height = video_height
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
            video_width=vid_cfg.get("width", 1152),
            video_height=vid_cfg.get("height", 768),
            working_dir=config.get("working_dir", ".working_dir/idea2video"),
        )

    # ────────────────────────────────────────────────────
    # Step: Generate character reference image
    # ────────────────────────────────────────────────────

    async def _get_character_reference(self, story: str, style: str) -> str:
        """Generate (or load cached) character reference image. Returns local file path."""
        ref_prompt_path = os.path.join(self.working_dir, "character_ref_prompt.txt")
        ref_img_path = os.path.join(self.working_dir, "character_reference.png")

        # Check cache
        if os.path.exists(ref_img_path) and os.path.exists(ref_prompt_path):
            logger.info("Character reference image loaded from cache.")
            return ref_img_path

        # Extract character description from story
        char_prompt = self.screenwriter.extract_character_description(story, style)
        with open(ref_prompt_path, "w") as f:
            f.write(char_prompt)

        # Generate reference image
        print(f"\n{'='*60}")
        print(f"🎨 CHARACTER REFERENCE PROMPT:\n{char_prompt}")
        print(f"{'='*60}\n")

        print("🖼️ Generating character reference image...")
        img_output = await self.image_generator.generate_single_image(
            prompt=char_prompt,
            size="1152x768",
        )
        img_output.save(ref_img_path)
        logger.info(f"Character reference saved: {ref_img_path}")
        print(f"✅ Character reference image saved: {ref_img_path}")

        return ref_img_path

    # ────────────────────────────────────────────────────
    # Scene Chaining: sequential generation with frame continuity
    # ────────────────────────────────────────────────────

    async def _extract_last_frame(self, video_path: str, output_path: str) -> str:
        """Extract the last frame from a video using ffmpeg. Returns output_path."""
        cmd = [
            "ffmpeg", "-y",
            "-sseof", "-1",
            "-i", video_path,
            "-frames:v", "1",
            "-update", "1",
            output_path,
        ]
        subprocess.run(cmd, capture_output=True, timeout=30, check=True)
        return output_path

    async def _generate_chained_scenes(self, scenes: list, reference_image: str, vw: int = 1152, vh: int = 768) -> list:
        """Generate scenes sequentially with frame chaining for continuity.

        Flow for each scene:
          1. Use current_image as ti2vid first frame -> generate video
          2. Extract last frame from video via ffmpeg
          3. Upload last frame via img2img API to get hosted URL
          4. Use img2img to generate next scene's starting frame
          5. Repeat until all scenes done

        Returns list of video file paths.
        """
        all_video_paths = []
        current_image = reference_image

        for scene_idx, scene_text in enumerate(scenes):
            print(f"\n{'─'*50}")
            print(f"🔗 Scene {scene_idx} (chained)")
            print(f"{'─'*50}")

            scene_dir = os.path.join(self.working_dir, f"scene_{scene_idx}")
            os.makedirs(scene_dir, exist_ok=True)
            video_path = os.path.join(scene_dir, "video.mp4")

            # Skip if video already exists
            if os.path.exists(video_path):
                logger.info(f"Scene {scene_idx} exists, skipping.")
                all_video_paths.append(video_path)
                last_frame_path = os.path.join(scene_dir, "last_frame.jpg")
                if os.path.exists(last_frame_path):
                    current_image = last_frame_path
                continue

            # Step A: Generate video with ti2vid using current_image as first frame
            print(f"  🎬 Generating video (ti2vid, scene {scene_idx})...")
            video_output = await self.video_generator.generate_single_video(
                prompt=scene_text,
                reference_image_paths=[current_image],
                duration=self.video_duration,
                width=vw,
                height=vh,
            )
            video_output.save(video_path)
            all_video_paths.append(video_path)
            print(f"  ✅ Video saved: {video_path}")

            # Step B: Extract last frame (only if there's a next scene)
            if scene_idx + 1 < len(scenes):
                last_frame_path = os.path.join(scene_dir, "last_frame.jpg")
                await self._extract_last_frame(video_path, last_frame_path)
                print(f"  🖼️  Last frame extracted: {last_frame_path}")

                # Step C: Upload last frame to get hosted URL
                last_frame_url = self.video_generator._resolve_image_ref(last_frame_path)
                print(f"  📤 Last frame uploaded to hosted URL")

                # Step D: Generate transition frame for next scene via img2img
                next_scene_text = scenes[scene_idx + 1]
                transition_prompt = (
                    f"Cinematic transition frame, blending the end of the current scene "
                    f"into the beginning of the next. Keep the same person and face exactly. "
                    f"Next scene: {next_scene_text[:200]}"
                )
                transition_path = os.path.join(scene_dir, f"transition_to_{scene_idx+1}.png")

                print(f"  🔄 Generating transition frame for scene {scene_idx+1}...")
                img_output = await self.image_generator.generate_single_image(
                    prompt=transition_prompt,
                    reference_image_paths=[last_frame_url],
                    size="768x1152",
                )
                img_output.save(transition_path)
                current_image = transition_path
                print(f"  ✅ Transition frame saved: {transition_path}")

        return all_video_paths

    # ────────────────────────────────────────────────────
    # Main pipeline
    # ────────────────────────────────────────────────────

    async def run(
        self,
        idea: str,
        user_requirement: str,
        style: str,
        reference_image: str = "",
        scene_chaining: bool = False,
        video_width: int = 0,
        video_height: int = 0,
    ) -> str:
        """Run the full pipeline and return the path to the final video.

        Args:
            idea: Creative concept / story idea.
            user_requirement: Constraints (audience, scenes, duration, etc.).
            style: Visual style (e.g. "Realistic", "Anime", "Cartoon").
            reference_image: Optional path or URL to a reference image.
                If provided, this image is used as the first-frame reference
                for ALL scene videos (ti2vid mode) instead of auto-generating
                a character reference. Supports local file paths and URLs.
            scene_chaining: If True, enable scene chaining mode — each scene's
                first frame is derived from the previous scene's last frame via
                image-to-image generation, creating visual continuity between
                scenes. This is sequential (not parallel). Recommended with
                10-second scenes and reference_image.
            video_width: Video width in pixels (0 = use default from config).
            video_height: Video height in pixels (0 = use default from config).
        """
        # Resolve video dimensions
        vw = video_width or self.video_width
        vh = video_height or self.video_height

        # ── Step 1: Develop Story ──
        story_path = os.path.join(self.working_dir, "story.txt")
        if os.path.exists(story_path):
            with open(story_path, "r") as f:
                story = f.read()
            logger.info("Story loaded from cache.")
        else:
            story = self.screenwriter.develop_story(idea, user_requirement, style)
            with open(story_path, "w") as f:
                f.write(story)
            logger.info(f"Story saved to {story_path}")

        print(f"\n{'='*60}")
        print(f"📖 STORY:\n{story[:500]}...")
        print(f"{'='*60}\n")

        # ── Step 2: Character Reference Image ──
        # This ensures character consistency across all scenes.
        # If the user provided a reference image, use it directly;
        # otherwise, auto-generate one from the story's character description.
        if reference_image:
            character_ref_path = reference_image
            logger.info(f"Using user-provided reference image: {reference_image}")
            print(f"📌 Using user-provided reference image: {reference_image}")
        else:
            character_ref_path = await self._get_character_reference(story, style)

        # ── Step 3: Write Script ──
        script_path = os.path.join(self.working_dir, "script.json")
        if os.path.exists(script_path):
            with open(script_path, "r") as f:
                scenes = json.load(f)
            logger.info(f"Script loaded from cache ({len(scenes)} scenes).")
        else:
            scenes = self.screenwriter.write_script(story, user_requirement, style)
            with open(script_path, "w") as f:
                json.dump(scenes, f, ensure_ascii=False, indent=2)
            logger.info(f"Script saved ({len(scenes)} scenes)")

        print(f"🎬 SCENES: {len(scenes)}")
        for i, scene in enumerate(scenes):
            print(f"  Scene {i}: {scene[:100]}...")
        print(f"📌 Character reference: {character_ref_path}")
        if scene_chaining:
            print(f"🔗 Mode: Scene Chaining (sequential with frame continuity)")
        print()

        # ── Step 4: For each scene -> generate video ──
        all_video_paths = []

        if scene_chaining:
            # Scene chaining: sequential generation with frame continuity
            all_video_paths = await self._generate_chained_scenes(
                scenes, character_ref_path, vw, vh
            )
        else:
            # Original parallel mode: same reference image for all scenes
            for scene_idx, scene_text in enumerate(scenes):
                print(f"\n{'─'*50}")
                print(f"🎥 Processing Scene {scene_idx}")
                print(f"{'─'*50}")

                scene_dir = os.path.join(self.working_dir, f"scene_{scene_idx}")
                os.makedirs(scene_dir, exist_ok=True)

                video_path = os.path.join(scene_dir, "video.mp4")

                # Skip if video already exists
                if os.path.exists(video_path):
                    logger.info(f"Scene {scene_idx} video exists, skipping.")
                    all_video_paths.append(video_path)
                    continue

                # Generate video using character reference image (ti2vid mode)
                print(f"  🎬 Generating video for scene {scene_idx} (ti2vid with character ref)...")
                video_output = await self.video_generator.generate_single_video(
                    prompt=scene_text,
                    reference_image_paths=[character_ref_path],
                    duration=self.video_duration,
                    width=vw,
                    height=vh,
                )
                video_output.save(video_path)
                logger.info(f"  ✅ Video saved: {video_path}")
                all_video_paths.append(video_path)

        # ── Step 5: Concatenate all scene videos ──
        final_video_path = os.path.join(self.working_dir, "final_video.mp4")
        if os.path.exists(final_video_path):
            logger.info(f"Final video already exists: {final_video_path}")
        elif len(all_video_paths) > 1:
            logger.info(f"Concatenating {len(all_video_paths)} scene videos...")
            clips = [VideoFileClip(p) for p in all_video_paths]
            final = concatenate_videoclips(clips, method="compose")
            final.write_videofile(final_video_path, logger="bar")
            for c in clips:
                c.close()
            logger.info(f"Final video: {final_video_path}")
        elif all_video_paths:
            shutil.copy2(all_video_paths[0], final_video_path)
            logger.info(f"Final video (single scene): {final_video_path}")
        else:
            raise RuntimeError("No videos were generated!")

        print(f"\n{'='*60}")
        print(f"🎉 FINAL VIDEO: {final_video_path}")
        print(f"{'='*60}\n")

        return final_video_path

    async def __call__(
        self,
        idea: str,
        user_requirement: str,
        style: str,
        reference_image: str = "",
        scene_chaining: bool = False,
        video_width: int = 0,
        video_height: int = 0,
    ) -> str:
        """Alias for run()."""
        return await self.run(
            idea=idea,
            user_requirement=user_requirement,
            style=style,
            reference_image=reference_image,
            scene_chaining=scene_chaining,
            video_width=video_width,
            video_height=video_height,
        )
