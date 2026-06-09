# ViMax-Agnes

**基于 Agnes AI 的智能视频生成工具**

> 基于 [ViMax](https://github.com/HKUDS/ViMax) 轻量改造，用 Agnes AI API 替代 Google Veo/Gemini 进行图像和视频生成。

[English](README.md) | 中文

## 功能特性

- **创意即视频**：只需提供创意想法、风格和简单需求
- **人物一致性**：先生成角色参考图，再通过 `ti2vid` 模式在所有场景中复用
- **全链路 Agnes 集成**：对话（故事/脚本）、图像生成、视频生成全部使用 Agnes AI
- **智能流水线**：故事 → 角色参考 → 脚本 → 场景视频 → 最终视频
- **缓存系统**：中间结果自动缓存，重复运行只生成缺失部分

## 系统架构

```
+------------------+
|   你的创意       |
| +（可选）        |
| 参考图片         |
+--------+--------+
         |
+-----------------+
|   编剧模块       | <- Agnes Chat API (agnes-2.0-flash)
|   故事 + 脚本    |
+--------+--------+
         |
+------------------+
| 角色参考图       | <- 用户提供，或通过
|                  |    Agnes Image API (agnes-image-2.1-flash)
+--------+--------+    从故事描述自动生成
         |
+-----------------+
| 视频生成器       | <- Agnes Video API (agnes-video-v2.0)
|  ti2vid 模式    |    每个场景使用同一参考图
|  （逐场景）      |    作为首帧保持一致性
+--------+--------+
         |
+-----------------+
|  视频拼接        | <- ffmpeg concat
|  最终成片        |
+-----------------+
```

### 为什么需要角色参考图？

没有参考图时，每个场景的文字生视频可能产生不同外观的角色。通过提供（或自动生成）一张参考图，然后在每个场景的 `ti2vid` 请求中作为首帧传入，角色/场景外观在整个视频中保持一致。

## 快速开始

### 1. 获取 Agnes API Key

在 [platform.agnes-ai.com](https://platform.agnes-ai.com) 注册。

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 设置 API Key

```bash
export AGNES_API_KEY="your-agnes-api-key"
```

或编辑 `configs/idea2video.yaml`。

### 4. 编辑你的创意

编辑 `main_idea2video.py`：

```python
idea = """
A robot pacing by a hot spring, wondering if it can swim
"""

user_requirement = """
No more than 5 scenes
"""

style = "Realistic"
```

### 5. 运行

```bash
python main_idea2video.py
```

### 6. 查看视频

输出：`.working_dir/idea2video/final_video.mp4`

## 参数说明

| 参数 | 描述 | 示例 |
|------|------|------|
| `idea` | 创意概念 | "一个机器人学习画画" |
| `user_requirement` | 约束条件（受众、场景数、时长） | "面向成人，最多5个场景" |
| `style` | 视觉风格 | "Cartoon"、"Realistic"、"Anime"、"Watercolor" |
| `reference_image` | *(可选)* 参考图片路径或URL | "./my_character.jpg" |

### 使用参考图片

默认情况下，流水线会从故事自动生成角色参考图。但你也可以提供自己的图片：

```python
reference_image = "./my_character.jpg"   # 本地文件
# 或
reference_image = "https://example.com/photo.jpg"  # URL
```

设置 `reference_image` 后：
- 提供的图片将作为所有场景视频的**首帧参考**（ti2vid 模式）
- 角色外观在整个视频中保持一致
- 跳过自动生成角色参考图的步骤

## 人物一致性与场景变化

### 实现原理

我们的视频生成使用**两阶段流水线**，在保持人物一致性的同时让每个场景各不相同：

```
阶段1: 文生图 (t2i) → 生成首帧
阶段2: 图生视频 (ti2vid) → 从首帧开始动画化
```

**阶段1 — 首帧生成 (t2i)**

每个场景使用独特的文本提示词描述具体内容（如"宝宝追蝴蝶"、"宝宝在浴缸里"）。但是，所有提示词末尾都共享一组固定的**风格关键词**：

```
"kawaii cartoon illustration style, soft pastel colors, rounded shapes,
 gentle warm lighting, children's picture book art, adorable chibi character
 design, simple clean background, Japanese anime cute style, high quality, detailed"
```

这些一致的风格关键词确保每张首帧共享相同的：
- **画风**（kawaii cartoon / chibi 卡通Q版）
- **色调**（soft pastel 柔和粉彩）
- **角色体型**（chubby chibi 圆胖Q版）
- **光照**（gentle warm 柔和暖光）
- **背景简洁度**（clean, uncluttered 干净简洁）

**阶段2 — 视频生成 (ti2vid)**

生成的首帧通过 `ti2vid`（图生视频）模式作为**参考图片**传入视频API。这会锁定视觉外观：

- 视频模型以首帧作为起始点
- 角色设计、颜色和风格从参考图继承
- 模型只负责生成动作/动画
- 防止模型"重新想象"出不同外观的角色

### 同一人物、不同场景 — 核心公式

```
+-----------------------------------------------------------+
|  每个场景独特的内容        |  所有场景共享的风格锁定      |
|  (场景特定内容)           |  (style lock-in)             |
+---------------------------+-----------------------------+
|  场景描述                 |  kawaii cartoon style        |
|  动作和姿势               |  soft pastel colors          |
|  环境/场景                |  rounded shapes              |
|  道具和物品               |  gentle warm lighting        |
|  情绪和表情               |  children's picture book     |
|                           |  adorable chibi design       |
|                           |  Japanese anime cute         |
+-----------------------------------------------------------+
```

### 为什么卡通/Q版风格效果好

卡通风格天生比写实风格更"标准化"：
- **简化的五官**：Q版角色有简化面部（圆点眼睛、小嘴巴），减少了变化性
- **大胆的配色**：粉彩调色板限制了色彩空间，使输出更统一
- **圆润的形状**：跨场景一致的几何语言
- **极简背景**：环境细节越少，视觉偏移的空间越小

### 最佳一致性实用技巧

1. **风格关键词保持完全一致** — 每个场景复制粘贴相同的风格后缀
2. **使用一致的角色描述词** — 例如始终说"chubby cartoon baby"，不要一个场景说"baby"另一个说"toddler"
3. **限制环境复杂度** — 简单背景 = 更少视觉噪音 = 更好的一致性
4. **批量生成首帧** — 减少生成间的模型偏移
5. **使用 ti2vid 模式（不用 t2v）** — 始终从图片开始，不要纯文字生视频

### 局限性

- **非像素级一致**：角色在服装颜色、发饰等方面可能有轻微变化
- **姿势相关**：同一角色在不同姿势下外观可能略有不同
- **场景相关**：背景变化不可避免地影响整体视觉感受
- **风格敏感**：卡通/Q版风格效果最好；写实风格需要真正的参考图锁定

## 已生成视频

### 📁 videos/ — 高清（HQ）输出

| 文件 | 场景数 | 时长 | 大小 | 描述 |
|------|--------|------|------|------|
| `baby_laugh_01_hq.mp4` | 8 | ~80秒 | 8.4MB | 宝宝笑第1集 - 阳光、躲猫猫、泡泡、小狗 |
| `baby_laugh_02_hq.mp4` | 8 | ~80秒 | 8.6MB | 宝宝笑第2集 - 不同欢乐场景 |
| `baby_laugh_03_hq.mp4` | 8 | ~80秒 | 6.4MB | 宝宝笑第3集 - 全新场景无字幕 |
| `baby_sing_hq.mp4` | 8 | ~80秒 | 5.0MB | 宝宝唱歌 - 音乐欢乐场景 |
| `baby_english_fruit_hq.mp4` | 8 | ~80秒 | 3.7MB | 宝宝学英文水果篇 - 带英文旁白 |
| `baby_count_10_hq.mp4` | 10 | ~100秒 | 5.5MB | 宝宝学识数1-10 - 中英双语+形状口诀 |

### 📁 prompts/ — 场景提示词 JSON 文件

| 文件 | 场景数 | 描述 |
|------|--------|------|
| `baby_laugh_01.json` | 8 | 宝宝笑第1集提示词 |
| `baby_laugh_02.json` | 8 | 宝宝笑第2集提示词 |
| `baby_laugh_03.json` | 8 | 宝宝笑第3集提示词（无字幕） |
| `baby_sing.json` | 8 | 宝宝唱歌提示词 |
| `baby_english_fruit.json` | 8 | 学英文水果篇提示词 |
| `baby_count_10.json` | 10 | 识数1-10提示词 |

### 📁 .working_dir/ — 原始生成数据（场景、首帧、任务ID）

每个视频项目有独立的子目录，包含：
- `subtitles.json` — 场景提示词
- `task_ids.json` — API 任务追踪
- `scenes/scene_N/` — 每个场景的首帧 + 原始视频

## 视频生成参数

| 参数 | 值 |
|------|-----|
| 分辨率 | 768 x 1152（竖屏） |
| 帧率 | 24 FPS |
| 每场景帧数 | 241（约10秒） |
| 视频模型 | agnes-video-v2.0 |
| 首帧模型 | agnes-image-2.1-flash |
| 高清压缩 | CRF 26, scale 480:720, x264 fast |
| 风格关键词 | kawaii cartoon, soft pastel colors, chibi, children's picture book art |

## TTS 语音旁白 (Edge TTS)

| 视频 | 英文声音 | 中文声音 | 内容 |
|------|---------|---------|------|
| baby_english_fruit | en-US-JennyNeural | - | 水果名称：Apple, Banana, Grapes... |
| baby_count_10 | en-US-JennyNeural | zh-CN-XiaoxiaoNeural | 数字 + 形状口诀（1像树根, 2像小鸭...） |

## Agnes API 详情

### 接口列表

| 用途 | 接口 | 模型 |
|------|------|------|
| 对话（故事/脚本） | POST `/v1/chat/completions` | agnes-2.0-flash |
| 角色参考图 | POST `/v1/images/generations` | agnes-image-2.1-flash |
| 图片上传转URL | POST `/v1/images/generations` (img2img) | agnes-image-2.1-flash |
| 场景视频 (ti2vid) | POST `/v1/videos` (image + mode=ti2vid) | agnes-video-v2.0 |
| 任务轮询 | GET `/v1/videos/{task_id}` | - |

### 时长控制

| 时长 | num_frames | frame_rate |
|------|-----------|------------|
| 5秒 | 121 | 24 |
| 10秒 | 241 | 24 |
| 15秒 | 361 | 24 |
| 18秒 | 441 | 24 |
| 20秒 | 441 | 22 |

## 项目结构

```
vimax-agnes/
+-- main_idea2video.py          # 入口 - 在这里编辑创意
+-- configs/
|   +-- idea2video.yaml         # API 配置
+-- agents/
|   +-- screenwriter.py         # LLM 驱动的故事/脚本/角色提取
+-- tools/
|   +-- image_generator_agnes_api.py  # Agnes 图像生成 (t2i + i2i)
|   +-- video_generator_agnes_api.py  # Agnes 视频生成 (t2v, ti2vid, keyframes)
|   +-- render_backend.py       # 基于配置的后端初始化
|   +-- protocols.py            # 类型契约
+-- interfaces/
|   +-- shot_description.py     # 镜头数据模型
|   +-- image_output.py         # 图像输出容器
|   +-- video_output.py         # 视频输出容器
+-- utils/
|   +-- image.py                # 图像下载 & base64 转换
|   +-- video.py                # 视频下载
+-- pipelines/
|   +-- idea2video_pipeline.py  # 主编排流水线
+-- prompts/                     # 场景提示词 JSON 文件
+-- videos/                     # 高清视频输出
+-- requirements.txt
+-- LICENSE
+-- README.md
+-- zh.md                       # 中文文档
```

## 流水线流程

1. **故事创作**：LLM 将创意扩展为结构化故事，包含详细的角色描述
2. **角色参考图**：使用提供的参考图，或从故事的角色描述自动生成
3. **脚本编写**：LLM 将故事拆分为多个场景，包含对话和动作
4. **场景视频**：每个场景使用参考图（ti2vid 模式）作为首帧生成视频
5. **视频拼接**：所有场景视频拼接为最终成片

## 致谢

- [ViMax](https://github.com/HKUDS/ViMax) — 原始智能视频生成框架
- [Agnes AI](https://platform.agnes-ai.com) — AI 生成 API
- [Edge TTS](https://github.com/rany2/edge-tts) — 文字转语音旁白

## 许可证

MIT
