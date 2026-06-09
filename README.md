# ViMax-Agnes

**Agentic Video Generation powered entirely by Agnes AI.**

> A lightweight adaptation of [ViMax](https://github.com/HKUDS/ViMax) that replaces Google Veo/Gemini with Agnes AI's API for image and video generation.

English | [中文](zh.md)

## Features

- **Idea -> Video**: Just provide a creative idea, style, and simple requirements
- **Character Consistency**: Generates a character reference image first, then reuses it across all scenes via `ti2vid` mode
- **Full Agnes Integration**: Uses Agnes AI for everything -- chat (story/script), image generation, and video generation
- **Smart Pipeline**: Story -> Character Reference -> Script -> Scene Videos -> Final Video
- **Cache System**: Intermediate results are cached -- re-run only generates missing parts

## Architecture

```
+------------------+
|   Your Idea     |
| + (Optional)    |
| Reference Image |
+--------+--------+
         |
+-----------------+
|  Screenwriter   | <- Agnes Chat API (agnes-2.0-flash)
|  Story + Script |
+--------+--------+
         |
+------------------+
| Character Ref    | <- User-provided image, or auto-generated
| Image            |    via Agnes Image API (agnes-image-2.1-flash)
+--------+--------+    from story's character description
         |
+-----------------+
|  Video Generator| <- Agnes Video API (agnes-video-v2.0)
|  ti2vid mode    |    Each scene uses the SAME reference image
|  (per scene)    |    as first frame for consistency
+--------+--------+
         |
+-----------------+
|  Concatenation  | <- moviepy
|  Final Video    |
+-----------------+
```

### Why Character Reference Image?

Without a reference image, each scene's text-to-video generation may produce a different-looking character. By providing (or auto-generating) ONE reference image, then passing it to every scene's `ti2vid` request as the first frame, the character/scene appearance stays consistent throughout the entire video.

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
| `reference_image` | *(Optional)* Path or URL of a reference image | "./my_character.jpg" |

### Using a Reference Image

By default, the pipeline auto-generates a character reference image from the story. But you can provide your own image instead:

```python
reference_image = "./my_character.jpg"   # local file path
# or
reference_image = "https://example.com/photo.jpg"  # URL
```

When `reference_image` is set:
- The provided image is used as the **first-frame reference** for ALL scene videos (ti2vid mode)
- Character/scene consistency is maintained across the entire video
- The auto-generation of character reference image is skipped

This is especially useful when you have a specific character or scene image that you want to keep consistent.

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
| Image Upload to URL | POST `/v1/images/generations` (img2img) | agnes-image-2.1-flash |
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
2. **Character Reference**: Uses the provided reference image, or auto-generates one from the story's character description
3. **Script Writing**: LLM divides the story into scenes with dialogue and actions
4. **Scene Videos**: Each scene generates a video using the reference image (ti2vid mode) as the first frame
5. **Concatenation**: All scene videos are joined into the final output

## Character Consistency & Scene Variation

### How It Works

Our video generation uses a **two-stage pipeline** to achieve character consistency across scenes while keeping each scene visually distinct:

```
Stage 1: Text-to-Image (t2i) → Generate First Frame
Stage 2: Image-to-Video (ti2vid) → Animate from First Frame
```

**Stage 1 — First Frame Generation (t2i)**

Each scene starts with a unique text prompt that describes the specific scene content (e.g., "baby chasing butterflies", "baby in bathtub"). However, ALL prompts share a fixed set of **style keywords** at the end:

```
"kawaii cartoon illustration style, soft pastel colors, rounded shapes,
 gentle warm lighting, children's picture book art, adorable chibi character
 design, simple clean background, Japanese anime cute style, high quality, detailed"
```

These consistent style keywords ensure that every first frame shares the same:
- Art style (kawaii cartoon / chibi)
- Color palette (soft pastel)
- Character body type (chubby chibi)
- Lighting (gentle warm)
- Background simplicity (clean, uncluttered)

**Stage 2 — Video Generation (ti2vid)**

The generated first frame is then passed to the video API as a **reference image** via `ti2vid` (image-to-video) mode. This locks the visual appearance:

- The video model uses the first frame as the starting point
- Character design, colors, and style are preserved from the reference
- Only the motion/animation is generated by the model
- This prevents the model from "reimagining" the character differently

### Same Character, Different Scenes — The Formula

```
┌─────────────────────────────────────────────────────────┐
│  UNIQUE per scene          │  SHARED across all scenes │
│  (scene-specific content)  │  (style lock-in)           │
├─────────────────────────────┼───────────────────────────┤
│  Scene description          │  kawaii cartoon style     │
│  Actions & poses            │  soft pastel colors       │
│  Environment/setting        │  rounded shapes            │
│  Props & objects            │  gentle warm lighting      │
│  Emotions & expressions     │  children's picture book   │
│                            │  adorable chibi design     │
│                            │  Japanese anime cute       │
└─────────────────────────────────────────────────────────┘
```

### Why This Works for Cartoon/Chibi Style

Cartoon styles are inherently more "standardized" than photorealistic styles:
- **Simple features**: Chibi characters have simplified faces (dot eyes, small mouth), reducing variability
- **Bold colors**: Pastel palettes limit the color space, making outputs more uniform
- **Rounded shapes**: Consistent geometric language across scenes
- **Minimal backgrounds**: Less environmental detail means less room for visual drift

### Practical Tips for Best Consistency

1. **Keep style keywords identical** — Copy-paste the same style suffix for every scene
2. **Use consistent character descriptors** — e.g., always say "chubby cartoon baby" not "baby" in one scene and "toddler" in another
3. **Limit environmental complexity** — Simpler backgrounds = less visual noise = better consistency
4. **Generate first frames in one batch** — Reduces model drift between generations
5. **Use ti2vid mode (not t2v)** — Always start from an image, never from text alone for video

### Limitations

- **Not pixel-perfect**: Characters may have slight variations in outfit color, hair accessory, etc. between scenes
- **Pose-dependent**: The same character in different poses may look slightly different
- **Scene-dependent**: Background changes inevitably affect overall visual feel
- **Style-sensitive**: Works best with cartoon/chibi styles; realistic styles require true reference image locking

## Generated Videos

### 📁 videos/ — High Quality (HQ) outputs

| File | Scenes | Duration | Size | Description |
|------|--------|----------|------|-------------|
| `baby_laugh_01_hq.mp4` | 8 | ~80s | 8.4MB | 宝宝笑第1集 - 阳光、躲猫猫、泡泡、小狗 |
| `baby_laugh_02_hq.mp4` | 8 | ~80s | 8.6MB | 宝宝笑第2集 - 不同欢乐场景 |
| `baby_laugh_03_hq.mp4` | 8 | ~80s | 6.4MB | 宝宝笑第3集 - 全新场景无字幕 |
| `baby_sing_hq.mp4` | 8 | ~80s | 5.0MB | 宝宝唱歌 - 音乐欢乐场景 |
| `baby_english_fruit_hq.mp4` | 8 | ~80s | 3.7MB | 宝宝学英文水果篇 - 带英文旁白 |
| `baby_count_10_hq.mp4` | 10 | ~100s | 5.5MB | 宝宝学识数1-10 - 中英双语+形状口诀 |

### 📁 prompts/ — Scene prompt JSON files

| File | Scenes | Description |
|------|--------|-------------|
| `baby_laugh_01.json` | 8 | 宝宝笑第1集提示词 |
| `baby_laugh_02.json` | 8 | 宝宝笑第2集提示词 |
| `baby_laugh_03.json` | 8 | 宝宝笑第3集提示词（无字幕） |
| `baby_sing.json` | 8 | 宝宝唱歌提示词 |
| `baby_english_fruit.json` | 8 | 学英文水果篇提示词 |
| `baby_count_10.json` | 10 | 识数1-10提示词 |

### 📁 .working_dir/ — Raw generation data (scenes, first frames, task IDs)

Each video project has its own subdirectory with:
- `subtitles.json` — scene prompts
- `task_ids.json` — API task tracking
- `scenes/scene_N/` — first frame + raw video per scene

## Video Generation Parameters

| Parameter | Value |
|-----------|-------|
| Resolution | 768 x 1152 (vertical) |
| FPS | 24 |
| Frames per scene | 241 (~10s) |
| Video model | agnes-video-v2.0 |
| First frame model | agnes-image-2.1-flash |
| HQ compression | CRF 26, scale 480:720, x264 fast |
| Style keywords | kawaii cartoon, soft pastel colors, chibi, children's picture book art |

## TTS Narration (Edge TTS)

| Video | English Voice | Chinese Voice | Content |
|-------|--------------|--------------|---------|
| baby_english_fruit | en-US-JennyNeural | - | Fruit names: Apple, Banana, Grapes... |
| baby_count_10 | en-US-JennyNeural | zh-CN-XiaoxiaoNeural | Numbers + shape mnemonics (1像树根, 2像小鸭...) |

## Credits

- [ViMax](https://github.com/HKUDS/ViMax) -- Original agentic video generation framework
- [Agnes AI](https://platform.agnes-ai.com) -- AI generation API
- [Edge TTS](https://github.com/rany2/edge-tts) -- Text-to-speech narration

## License

MIT
