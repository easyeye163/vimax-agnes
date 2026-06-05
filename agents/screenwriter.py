"""Screenwriter agent — develops story and writes scene scripts using Agnes chat API."""

import json
import logging
import requests
from typing import List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

BASE_URL = "https://apihub.agnes-ai.com/v1"


class Screenwriter:
    """Develops stories from ideas and writes scripts scene by scene."""

    def __init__(self, api_key: str, model: str = "agnes-2.0-flash"):
        self.api_key = api_key
        self.model = model
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _chat(self, system_prompt: str, user_prompt: str) -> str:
        """Call Agnes chat API and return content."""
        resp = requests.post(
            f"{BASE_URL}/chat/completions",
            headers=self.headers,
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.7,
                "max_tokens": 4096,
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    def _chat_json(self, system_prompt: str, user_prompt: str) -> dict:
        """Call chat API and parse JSON response."""
        content = self._chat(system_prompt, user_prompt)
        # Try to extract JSON from response
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1]
            if content.endswith("```"):
                content = content[:-3]
        return json.loads(content)

    def develop_story(self, idea: str, user_requirement: str, style: str) -> str:
        """Expand an idea into a full story."""
        system_prompt = """\
You are a seasoned creative story generation expert. You expand ideas into \
well-structured stories with clear scenes, characters, and dialogue.

[Output] A complete story in paragraphs with:
- Story Title
- Target Audience & Genre
- Story Outline (1 paragraph)
- Main Characters Introduction
- Full Story Narrative (Introduction → Development → Climax → Conclusion)

IMPORTANT: Write the story in the SAME LANGUAGE as the input idea.
Keep it concise but vivid, suitable for adaptation into short video scenes.
"""
        user_prompt = f"""\
<idea>
{idea}
</idea>

<user_requirement>
{user_requirement}
</user_requirement>

<style>
{style}
</style>
"""
        logger.info("[Screenwriter] Developing story...")
        story = self._chat(system_prompt, user_prompt)
        logger.info(f"[Screenwriter] Story developed: {len(story)} chars")
        return story

    def write_script(self, story: str, user_requirement: str, style: str) -> List[str]:
        """Write a script divided into scenes from a story."""
        system_prompt = """\
You are a professional scriptwriter. Adapt the given story into a video script \
divided by scenes. Each scene must share the same time and location.

[Output Format] Return a JSON object:
{
  "scenes": [
    "Scene 1 narrative with character actions and dialogue...",
    "Scene 2 narrative...",
    ...
  ]
}

Rules:
- Each scene is a self-contained paragraph describing location, characters, actions, and dialogue.
- Character names in descriptions should be enclosed in angle brackets, e.g. <Tom>.
- Dialogue format: <CharacterName> says: "dialogue text"
- Include visual details useful for generating images (lighting, mood, composition).
- IMPORTANT: Output the scene text in the SAME LANGUAGE as the input story.
- Number of scenes must respect the user requirement constraints.
"""
        user_prompt = f"""\
<story>
{story}
</story>

<user_requirement>
{user_requirement}
</user_requirement>

<style>
{style}
</style>
"""
        logger.info("[Screenwriter] Writing script...")
        result = self._chat_json(system_prompt, user_prompt)
        scenes = result.get("scenes", [])
        logger.info(f"[Screenwriter] Script written: {len(scenes)} scenes")
        return scenes

    def design_shots_for_scene(self, scene_text: str, style: str, max_shots: int = 5) -> list:
        """Design shot-level storyboard for a single scene."""
        system_prompt = """\
You are a professional storyboard artist. Design shots for a single scene.

[Output Format] Return a JSON object:
{
  "shots": [
    {
      "visual_desc": "Overall visual description of the shot",
      "variation_type": "large|medium|small",
      "ff_desc": "First frame — static snapshot description",
      "lf_desc": "Last frame — static snapshot description",
      "motion_desc": "Motion between frames. Include dialogue as: <Char> says: \\"text\\"",
      "audio_desc": "[Sound Effect] description"
    }
  ]
}

Rules:
- First shot must establish the scene environment.
- Last shot should end the scene naturally.
- variation_type: "large" (big scene change), "medium" (new element appears), "small" (minor movement)
- First/last frame descriptions are STATIC images — no motion words.
- Motion description includes all movement AND dialogue.
- Include rich visual details for image generation (lighting, colors, composition).
- Output in the SAME LANGUAGE as the input scene.
"""
        user_prompt = f"""\
<scene>
{scene_text}
</scene>

<style>{style}</style>
<max_shots>{max_shots}</max_shots>
"""
        logger.info(f"[Screenwriter] Designing shots for scene...")
        result = self._chat_json(system_prompt, user_prompt)
        shots = result.get("shots", [])
        logger.info(f"[Screenwriter] Designed {len(shots)} shots")
        return shots
