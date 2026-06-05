# ViMax-Agnes

**Agentic Video Generation powered entirely by Agnes AI.**

> A lightweight adaptation of [ViMax](https://github.com/HKUDS/ViMax) that replaces Google Veo/Gemini with Agnes AI's API for image and video generation.

## Features

- **Idea -> Video**: Just provide a creative idea, style, and simple requirements
- **Full Agnes Integration**: Uses Agnes AI for everything -- chat (story/script planning), image generation, and video generation
- **Smart Pipeline**: Story -> Script -> Shots -> First/Last Frame Images -> Videos -> Final Video
- **Character Consistency**: Uses `ti2vid` mode (image-to-video) and `keyframes` mode for visual continuity
- **Cache System**: Intermediate results (story, script, images, videos) are cached -- re-run only generates missing parts

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
+-----------------+
|  Shot Planner   | <- Agnes Chat API
|  Storyboard     |
+--------+--------+
         |
+-----------------+
|  Image Generator| <- Agnes Image API (agnes-image-2.1-flash)
|  First/Last Frame|
+--------+--------+
         |
+-----------------+
|  Video Generator| <- Agnes Video API (agnes-video-v2.0)
|  ti2vid/keyframes|
+--------+--------+
         |
+-----------------+
|  Concatenation  | <- moviepy
|  Final Video    |
+-----------------+
```

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

### 4. Run!

Edit `main_idea2video.py` with your idea:

```python
idea = """
A robot pacing by a hot spring, wondering if it can swim
"""

user_requirement = """
No more than 5 scenes
"""

style = "Realistic"
```

Then:

```bash
python main_idea2video.py
```

### 5. Find Your Video

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
    default_duration: 5  # seconds per shot
```

Supported: 5s, 10s, 15s, 18s, 20s

## Video Generation Modes

The pipeline automatically selects the best mode:

| Variation | Mode | Reference Images |
|-----------|------|-----------------|
| `large` | keyframes | First frame + Last frame |
| `medium` | keyframes | First frame + Last frame |
| `small` | ti2vid | First frame only |

## Agnes API Details

### Endpoints

| Purpose | Endpoint | Model |
|---------|----------|-------|
| Chat (Story/Script) | POST `/v1/chat/completions` | agnes-2.0-flash |
| Text-to-Image | POST `/v1/images/generations` | agnes-image-2.1-flash |
| Image-to-Image | POST `/v1/images/generations` (extra_body) | agnes-image-2.0-flash |
| Text-to-Video | POST `/v1/videos` | agnes-video-v2.0 |
| Image-to-Video | POST `/v1/videos` (image + mode=ti2vid) | agnes-video-v2.0 |
| Keyframes Video | POST `/v1/videos` (extra_body: image[] + mode=keyframes) | agnes-video-v2.0 |
| Task Polling | GET `/v1/videos/{task_id}` | - |

### Duration Control

Video duration is controlled by `num_frames` and `frame_rate`:

| Duration | num_frames | frame_rate |
|----------|-----------|------------|
| 5s | 121 | 24 |
| 10s | 241 | 24 |
| 15s | 361 | 24 |
| 18s | 441 | 24 |
| 20s | 441 | 22 |

Note: `num_frames` must follow the 8n+1 pattern, max 441.

## Project Structure

```
vimax-agnes/
+-- main_idea2video.py          # Entry point - edit your idea here
+-- configs/
|   +-- idea2video.yaml         # API configuration
+-- agents/
|   +-- screenwriter.py         # LLM-powered story/script generation
+-- tools/
|   +-- image_generator_agnes_api.py  # Agnes image generation
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

## Credits

- [ViMax](https://github.com/HKUDS/ViMax) -- Original agentic video generation framework
- [Agnes AI](https://platform.agnes-ai.com) -- AI generation API

## License

MIT
