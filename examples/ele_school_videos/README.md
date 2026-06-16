# 小学生教育视频生成示例

多场景教育短视频自动生成流水线：图片提示词 → 首帧生成 → 图生视频 → 连续TTS配音 → 拼接压缩。

## 效果预览

| 集数 | 主题 | 时长 | 分辨率 | 配音 |
|------|------|------|--------|------|
| 🔢 ele_math | 数学乐园 | 40秒 | 1280×704 | 连续中文 |
| 🔬 ele_science | 科学探索 | 40秒 | 1280×704 | 连续中文 |
| 🌍 ele_nature | 自然探索 | 40秒 | 1280×704 | 连续中文 |
| 📖 ele_english | 英语学习 | 40秒 | 1280×704 | 连续中文 |
| ⚽ ele_pe | 体育运动 | 40秒 | 1280×704 | 连续中文 |
| 📝 ele_study | 学习方法 | 40秒 | 1280×704 | 连续中文 |

每集 **8个场景 × 5秒 = 40秒**，中英文提示词驱动图片生成，连续中文TTS配音。

- 前三集（math/science/nature）侧重知识启蒙，激发学习兴趣
- 后三集（english/pe/study）侧重学习方法，培养良好学习习惯

## 目录结构

```
ele_school_videos/
├── pipeline.py              # 核心流水线脚本（4阶段）
├── ele_math/
│   ├── prompts.json         # 8个场景的图片生成提示词
│   └── tts.json             # 连续中文旁白 + TTS配置
├── ele_science/
│   ├── prompts.json
│   └── tts.json
├── ele_nature/
│   ├── prompts.json
│   └── tts.json
├── ele_english/
│   ├── prompts.json
│   └── tts.json
├── ele_pe/
│   ├── prompts.json
│   └── tts.json
├── ele_study/
│   ├── prompts.json
│   └── tts.json
└── README.md                # 本文件
```

## 快速开始

### 1. 配置API Key

编辑 `pipeline.py`，替换API Key：

```python
KEY = "your-api-key-here"
```

### 2. 一键执行

```bash
# 全流程（生成图片 → 提交视频 → 轮询下载 → TTS配音 + 拼接）
python3 pipeline.py all

# 分步执行
python3 pipeline.py frames    # 仅生成首帧图片
python3 pipeline.py submit    # 仅提交视频任务
python3 pipeline.py poll      # 仅轮询下载
python3 pipeline.py process   # 仅TTS + 拼接 + 压缩
```

## 四阶段流水线详解

### 阶段1: 生成首帧图片 (`frames`)

读取每个场景的英文提示词，调用 Agnes 图片生成API：

```
POST /v1/images/generations
{
  "model": "agnes-image-2.1-flash",
  "prompt": "<场景英文提示词>",
  "size": "1280x720",
  "n": 1
}
```

每个提示词生成一张1280×720的首帧图片（PNG）。

### 阶段2: 提交视频任务 (`submit`)

将首帧图片转为JPEG → Base64编码 → 提交图生视频：

```
POST /v1/videos
{
  "model": "agnes-video-v2.0",
  "prompt": "<场景英文提示词，截断300字符>",
  "image": "<base64编码的JPEG图片>",
  "size": "1280x720"
}
```

**关键优化**：
- **PNG→JPEG**：`ffmpeg -q:v 5` 可将1.6MB PNG降至163KB，避免API超时
- **POST timeout=180s**：视频提交需要较长超时，60秒不够
- **并行提交**：ThreadPoolExecutor(max_workers=6) 同时提交24个场景

### 阶段3: 轮询下载 (`poll`)

每5分钟检查一次，视频完成后自动下载：

```
GET /v1/videos/{task_id}
→ status: "queued" | "in_progress" | "completed" | "failed"
→ remixed_from_video_id: "<视频下载URL>"  (completed时)
```

### 阶段4: TTS配音 + 拼接 (`process`)

**★ 连续配音设计（关键）**

不按场景分段配音，而是整集一条连续叙述：

```json
{
  "narration": "欢迎来到数学乐园！数学就在我们身边...你就是最棒的小数学家！",
  "tts_config": {
    "voice": "zh-CN-XiaoxiaoNeural",
    "rate": "-5%",
    "duration": 35.6,
    "video_duration": 40.4
  }
}
```

**为什么不用分段配音？**
- 每个场景仅5秒，分段配音会导致每5秒断开，听起来像PPT翻页
- 连续配音（35-39秒）自然过渡，配合画面切换更流畅
- edge-tts生成一条完整音频，ffmpeg填充到41秒后与视频合并

**TTS时长控制**：
- 文案长度决定TTS时长，需匹配视频时长（40秒）
- 中文语速约每秒5-6字，35秒约175-210字
- 建议控制在视频时长的85-95%，留1-2秒自然结尾

## 提示词设计要点

### 图片提示词（英文）

教育类视频提示词的关键要素：

```
主体描述 + 场景背景 + 风格限定 + 画质标注
```

示例：
```
A colorful cartoon classroom scene with a cheerful young girl counting 
colorful building blocks, bright warm lighting, children's educational 
style, 4k quality
```

**风格关键词**：
- `cartoon` / `children's educational style` — 儿童动画风格
- `colorful` / `bright warm lighting` — 明亮温暖色调
- `educational` / `cheerful` / `playful` — 教育趣味氛围

### 旁白文案（中文）

连续叙述结构：

```
开场欢迎 → 场景描述（串联8个场景）→ 总结鼓励
```

示例结构：
1. **开场**（3-4秒）："欢迎来到XX！"
2. **场景串联**（25-30秒）：自然过渡描述每个场景内容
3. **总结**（3-5秒）："你就是最棒的XX！"

## API参考

| 接口 | 方法 | 模型 | 用途 |
|------|------|------|------|
| `/v1/images/generations` | POST | agnes-image-2.1-flash | 文生图（首帧） |
| `/v1/videos` | POST | agnes-video-v2.0 | 图生视频 |
| `/v1/videos/{id}` | GET | - | 轮询状态 |

**注意事项**：
- 视频输出固定1280×704横屏（非1280×720）
- 视频URL字段为 `remixed_from_video_id`
- POST请求建议 timeout ≥ 180秒
- PNG图片需转为JPEG再提交（降低payload体积）

## 扩展说明

### 添加新集数

1. 创建新目录 `ele_xxx/`
2. 编写 `prompts.json`（8个场景提示词）
3. 编写 `tts.json`（旁白文案 + TTS配置）
4. 在 `pipeline.py` 的 `EPISODES` 列表中添加配置
5. 运行 `python3 pipeline.py all`

### 修改配音风格

在 `tts.json` 中调整：
- `voice`: 切换TTS声音（如 `zh-CN-YunxiNeural` 男声）
- `rate`: 语速（`-5%` 稍慢，`+10%` 稍快）
- `narration`: 修改文案内容

### 中英双语配音

如需中英双语，在阶段4中拼接两段TTS：

```python
# 中文TTS
asyncio.run(edge_tts.Communicate(zh_text, "zh-CN-XiaoxiaoNeural", rate="-5%").save(zh_mp3))
# 英文TTS
asyncio.run(edge_tts.Communicate(en_text, "en-US-JennyNeural", rate="-5%").save(en_mp3))
# 用ffmpeg concat连接，中间加0.5秒静音间隔
```

> 注意：双语配音总时长约80秒，远超40秒视频，建议仅用中文配音或缩短文案。
