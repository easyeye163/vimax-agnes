# ViMax-Agnes

**Agentic Video Generation powered entirely by Agnes AI.**

> A lightweight adaptation of [ViMax](https://github.com/HKUDS/ViMax) that replaces Google Veo/Gemini with Agnes AI's API for image and video generation.

## Features

- **Idea -> Video**: Just provide a creative idea, style, and simple requirements
- **Character Consistency**: Generates a character reference image first, then reuses it across all scenes via `ti2vid` mode
- **Full Agnes Integration**: Uses Agnes AI for everything -- chat (story/script), image generation, and video generation
- **Smart Pipeline**: Story -> Character Reference -> Script -> Scene Videos -> Final Video
- **Cache System**: Intermediate results are cached -- re-run only generates missing parts

## Architecture

```
+-----------------+
|   Your Idea     |
+--------+--------+
         |
+-----------------+
|  Screenwriter   | <- Agnes Chat API (agnes-2.0-flash)
|  Story + Script |
+--------+--------+
         |
+------------------+
| Character Ref    | <- Agnes Image API (agnes-image-2.1-flash)
| Image Generation |    Extract character description from story,
+--------+--------+    generate a reference image for consistency
         |
+-----------------+
|  Video Generator| <- Agnes Video API (agnes-video-v2.0)
|  ti2vid mode    |    Each scene uses the SAME reference image
|  (per scene)    |    to maintain character appearance
+--------+--------+
         |
+-----------------+
|  Concatenation  | <- moviepy
|  Final Video    |
+-----------------+
```

### Why Character Reference Image?

Without a reference image, each scene's text-to-video generation may produce a different-looking character. By generating ONE reference image of the main character first, then passing it to every scene's `ti2vid` request, the character's appearance stays consistent throughout the entire video.

## Quick Start

### 1. Get Agnes API Key

Register at [platform.agnes-ai.com](https://platform.agnes-ai.com).

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Set API Key

```bash
export AGNES_API_KEY="your-agnes-api-key"
```

Or edit `configs/idea2video.yaml`.

### 4. Edit Your Idea

Edit `main_idea2video.py`:

```python
idea = """
A robot pacing by a hot spring, wondering if it can swim
"""

user_requirement = """
No more than 5 scenes
"""

style = "Realistic"
```

### 5. Run!

```bash
python main_idea2video.py
```

### 6. Find Your Video

Output: `.working_dir/idea2video/final_video.mp4`

## Parameters

| Parameter | Description | Example |
|-----------|-------------|---------|
| `idea` | Your creative concept | "A robot learns to paint" |
| `user_requirement` | Constraints (audience, scenes, duration) | "For adults, 5 scenes max" |
| `style` | Visual style | "Cartoon", "Realistic", "Anime", "Watercolor" |

### Video Duration

Edit `configs/idea2video.yaml`:

```yaml
video_generator:
  init_args:
    default_duration: 5  # seconds per scene
```

Supported: 5s, 10s, 15s, 18s, 20s

## Agnes API Details

### Endpoints

| Purpose | Endpoint | Model |
|---------|----------|-------|
| Chat (Story/Script) | POST `/v1/chat/completions` | agnes-2.0-flash |
| Character Reference | POST `/v1/images/generations` | agnes-image-2.1-flash |
| Scene Video (ti2vid) | POST `/v1/videos` (image + mode=ti2vid) | agnes-video-v2.0 |
| Task Polling | GET `/v1/videos/{task_id}` | - |

### Duration Control

| Duration | num_frames | frame_rate |
|----------|-----------|------------|
| 5s | 121 | 24 |
| 10s | 241 | 24 |
| 15s | 361 | 24 |
| 18s | 441 | 24 |
| 20s | 441 | 22 |

## Project Structure

```
vimax-agnes/
+-- main_idea2video.py          # Entry point - edit your idea here
+-- configs/
|   +-- idea2video.yaml         # API configuration
+-- agents/
|   +-- screenwriter.py         # LLM-powered story/script/character extraction
+-- tools/
|   +-- image_generator_agnes_api.py  # Agnes image generation (t2i + i2i)
|   +-- video_generator_agnes_api.py  # Agnes video generation (t2v, ti2vid, keyframes)
|   +-- render_backend.py       # Config-based backend initialization
|   +-- protocols.py            # Type contracts
+-- interfaces/
|   +-- shot_description.py     # Shot data model
|   +-- image_output.py         # Image output container
|   +-- video_output.py         # Video output container
+-- utils/
|   +-- image.py                # Image download & b64 conversion
|   +-- video.py                # Video download
+-- pipelines/
|   +-- idea2video_pipeline.py  # Main orchestration pipeline
+-- requirements.txt
+-- LICENSE
+-- README.md
```

## Pipeline Flow

1. **Story Development**: LLM expands your idea into a structured story with detailed character descriptions
2. **Character Reference**: LLM extracts character appearance description -> generates a reference image
3. **Script Writing**: LLM divides the story into scenes with dialogue and actions
4. **Scene Videos**: Each scene generates a video using the character reference image (ti2vid mode)
5. **Concatenation**: All scene videos are joined into the final output

## Credits

- [ViMax](https://github.com/HKUDS/ViMax) -- Original agentic video generation framework
- [Agnes AI](https://platform.agnes-ai.com) -- AI generation API

## License

MIT
