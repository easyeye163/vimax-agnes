# ViMax-Agnes 🎬🐱

**Agentic Video Generation powered entirely by Agnes AI.**

> A lightweight adaptation of [ViMax](https://github.com/HKUDS/ViMax) that replaces Google Veo/Gemini with Agnes AI's free unlimited API for image and video generation.

## ✨ Features

- **Idea → Video**: Just provide a creative idea, style, and simple requirements
- **Full Agnes Integration**: Uses Agnes AI for everything — chat (story/script planning), image generation, and video generation
- **Smart Pipeline**: Story → Script → Shots → First/Last Frame Images → Videos → Final Video
- **Character Consistency**: Uses `ti2vid` mode (image-to-video) and `keyframes` mode for visual continuity
- **Cache System**: Intermediate results (story, script, images, videos) are cached — re-run only generates missing parts
- **Free & Unlimited**: Powered by Agnes AI's free API

## 🏗️ Architecture

```
┌─────────────┐
│   Your Idea  │
└──────┬──────┘
       ▼
┌─────────────────┐
│  Screenwriter    │ ← Agnes Chat API (agnes-2.0-flash)
│  Story + Script  │
└──────┬──────────┘
       ▼
┌─────────────────┐
│  Shot Planner    │ ← Agnes Chat API
│  Storyboard      │
└──────┬──────────┘
       ▼
┌─────────────────┐
│  Image Generator │ ← Agnes Image API (agnes-image-2.1-flash)
│  First/Last Frame│
└──────┬──────────┘
       ▼
┌─────────────────┐
│  Video Generator │ ← Agnes Video API (agnes-video-v2.0)
│  ti2vid/keyframes│
└──────┬──────────┘
       ▼
┌─────────────────┐
│  Concatenation   │ ← moviepy
│  Final Video     │
└─────────────────┘
```

## 🚀 Quick Start

### 1. Get Agnes API Key

Register at [platform.agnes-ai.com](https://platform.agnes-ai.com) — free, no credit card needed.

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

```bash
python main_idea2video.py
```

### 5. Find Your Video

Output: `.working_dir/idea2video/final_video.mp4`

## ⚙️ Configuration

Edit `main_idea2video.py`:

```python
idea = \
"""
If a cat and a dog are best friends, what would happen when they meet a new cat?
"""

user_requirement = \
"""
For children, do not exceed 3 scenes.
"""

style = "Cartoon"
```

### Parameters

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

## 🎥 Video Generation Modes

The pipeline automatically selects the best mode:

| Variation | Mode | Reference Images |
|-----------|------|-----------------|
| `large` | keyframes | First frame + Last frame |
| `medium` | keyframes | First frame + Last frame |
| `small` | ti2vid | First frame only |

## 🔄 Pipeline Flow

1. **Story Development**: LLM expands your idea into a structured story
2. **Script Writing**: LLM divides the story into scenes with dialogue and actions
3. **Shot Design**: LLM creates shot-level storyboards with first/last frame descriptions
4. **Image Generation**: Agnes generates first frame (and last frame for keyframe shots)
5. **Video Generation**: Agnes generates video clips from frames
6. **Concatenation**: All scene videos are joined into the final output

## 📁 Output Structure

```
.working_dir/idea2video/
├── story.txt              # Generated story
├── script.json            # Scene scripts
├── scene_0/
│   ├── shots.json          # Shot descriptions
│   ├── shot_0/
│   │   ├── first_frame.png
│   │   ├── last_frame.png
│   │   └── video.mp4
│   ├── shot_1/
│   │   └── ...
│   └── scene_video.mp4
├── scene_1/
│   └── ...
└── final_video.mp4         # ← Final output!
```

## 🙏 Credits

- [ViMax](https://github.com/HKUDS/ViMax) — Original agentic video generation framework
- [Agnes AI](https://platform.agnes-ai.com) — Free unlimited AI generation API

## License

MIT
