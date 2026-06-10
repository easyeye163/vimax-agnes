# 🎬 Baby Educational Videos

儿童卡通教育短视频，使用 AI 图像/视频生成 + TTS 配音制作。

## 视频系列

| 系列 | 场景数 | 内容 | 目录 |
|------|--------|------|------|
| 🎨 颜色篇 | 8 | 红橙黄绿蓝紫粉彩虹 | `colors/` |
| 🐾 动物篇 | 8 | 猫狗鹦鹉长颈鹿青蛙大象鱼 | `animals/` |
| 🚗 交通篇 | 8 | 汽车火车公交车飞机轮船消防车自行车火箭 | `transport/` |
| 👨‍👩‍👧‍👦 家人篇 | 8 | 爸爸妈妈爷爷奶奶外公外婆舅舅阿姨 | `family/` |
| 🔤 ABC第1集 | 8 | A-H (Apple,Bear,Cat,Dog,Egg,Fish,Grapes,Hat) | `abc1/` |
| 🔤 ABC第2集 | 8 | I-P (Ice cream,Juice,Kite,Lion,Moon,Nest,Orange,Panda) | `abc2/` |
| 🔤 ABC第3集 | 8 | Q-X (Queen,Rainbow,Star,Tiger,Umbrella,Violin,Watermelon,Xylophone) | `abc3/` |
| 🔤 ABC第4集 | 8 | Y-Z+数字1-6 (Yacht,Zebra,One~Six) | `abc4/` |
| 🎉 额外 | 3 | 宝宝笑、宝宝笑2、宝宝唱歌 | `extra/` |

## 目录结构

每个系列目录包含：

```
series_name/
├── prompts.json    # 每个场景的图像/视频生成提示词
├── tts.json        # 中英文TTS配音文本
├── raw/            # 原始高清视频（768x1152, 未压缩）
│   └── *.mp4
└── hq/             # 微信优化版（480x720, CRF压缩）
    └── *.mp4
```

## 技术参数

- **图像生成**: Agnes Image 2.1 Flash (1024x1024)
- **视频生成**: Agnes Video v2.0 (ti2vid, 768x1152, 24fps, 10s/场景)
- **TTS**: Edge TTS - 中文(zh-CN-XiaoxiaoNeural) + 英文(en-US-JennyNeural)
- **配音策略**: 中文先播 + 英文简短后播，确保10秒内不串场景
- **压缩**: CRF 26-30, H.264, AAC 128kbps, 微信友好 (<10MB)

## API

使用 [Agnes AI API](https://apihub.agnes-ai.com/v1) 进行图像和视频生成。
