# BatchReplaceAudioBurnSub

**Batch video repack tool** — Replace original audio with translated audio, burn/embed subtitles, and upscale in one pass.

Built for processing translated educational/trading videos: remove original audio → replace with `_translated.mp3` → burn `_translated.srt` subtitles → scale to target resolution → HEVC hardware encode.

## Features

- **Batch replace audio** — Match `_translated.mp3` files to videos automatically (numbered prefix or similarity)
- **Burn subtitles (hardsub)** — Dark-background subtitles burnt into video, auto-sized font (Microsoft YaHei)
- **Embed subtitles (softsub)** — Keep subtitles as switchable track in output MP4
- **Voice enhancement** — 4 EQ presets: Clear, Warm, De-ess, Conference room
- **Parallel encoding** — Multi-stream HEVC AMF hardware encoding (default 4 streams)
- **Rate control** — VBR (smart), CBR (fixed), CQ (constant quality)
- **Resolution** — 720p / 1080p / 2K / 4K
- **Resume support** — Skips already-encoded videos (>1MB)
- **Real-time progress** — Per-video and overall progress bars

## What it does

```
Input:  001_my_video.mp4 + 001_my_video_translated.mp3 + 001_my_video_translated.srt
        ↓
Output: _video_out/001_my_video_1080p.mp4
        (HEVC, translated audio, optional hardsub/softsub subtitles)
```

## Quick Start

### Option 1: Download the pre-built EXE (recommended)

Grab the latest EXE from the **[Releases page](https://github.com/cc9527-1/-BatchReplaceAudioBurnSub/releases)**:

1. Download `BatchReplaceAudioBurnSub.exe`
2. Double-click to launch
3. Select your video folder → Scan → select videos → START

### Option 2: Run from source

```bash
pip install -r requirements.txt
python gui.py
```

Requires Python 3.7+ and FFmpeg 7.0+ with `hevc_amf` support.

### Option 3: CLI (encode_tool.py)

A lightweight CLI version is available in the `cli/` directory for headless/server use.

## Requirements

- **Windows** (AMF hardware encoding requires AMD GPU + Windows)
- **FFmpeg 8.0+** — place at `%LOCALAPPDATA%\ffmpeg\ffmpeg-8.0.1-essentials_build\bin\ffmpeg.exe` or add to PATH
- **AMD GPU** with hevc_amf encoder (optional, falls back to CPU libx264/libx265)
- Python 3.7+ (if running from source)
  - No extra Python packages needed (uses stdlib + tkinter)

## File matching logic

| File | Pattern | Example |
|------|---------|---------|
| Video | any `.mp4/.mkv/.mov/...` | `001 How to trade GC.mp4` |
| Audio | `_translated.mp3` / `_翻译.mp3` / `_zh.mp3` / `_chinese.mp3` | `001 How to trade GC_translated.mp3` |
| Subtitle | `_translated.srt` / `_翻译.srt` / etc. | `001 How to trade GC_translated.srt` |

Matching is done by:
1. **Numbered prefix** — if video is `001 xxxx.mp4`, matches `001 xxxx_translated.mp3`
2. **Similarity** — falls back to fuzzy string matching

## Settings

| Option | Values | Default |
|--------|--------|---------|
| Resolution | 720p / 1080p / 2K / 4K | 1080p |
| Bitrate | 4M / 6M / 8M / 10M / 12M / 15M / 20M | 8M |
| RC Mode | VBR (smart) / CBR (fixed) / CQ (constant quality) | VBR (smart) |
| Encoder | AMD GPU (hevc_amf) / CPU (libx264) | AMD GPU |
| Parallel | 2 / 3 / 4 / 5 / 6 | 4 |
| Voice EQ | None / Clear / Warm / De-ess / Conference | None |

### RC Mode Guide

| Mode | Size | Quality | Best for |
|------|------|---------|----------|
| **CQ** (constant quality) | Smallest (70% less than CBR) | Excellent | Slides, screencasts, PPT |
| **VBR** (smart) | Moderate | Best balance | General purpose (recommended) |
| **CBR** (fixed) | Largest | Most stable | Live streaming, strict bitrate |

## Output

All encoded files go to `_video_out/` inside your source directory:
```
your_video_folder/
├── 001 video.mp4
├── 001 video_translated.mp3
├── 001 video_translated.srt
└── _video_out/
    └── 001 video_1080p.mp4    ← output
```

## v4.1 Changelog

- New RC mode selector (VBR/CBR/CQ)
- CQ mode reduces file size by ~70%, ideal for slide content
- Default VBR bitrate reduced to 8M (9% smaller than CBR 12M)
- Default parallel streams: 4 (balanced CPU/GPU)
- GPU hardware decoding (d3d11va) reduces CPU load
- 2 threads per FFmpeg instance (~50% total CPU at 4-way parallel)

## v4.0 fixes

- Fixed subtitle path encoding issues with Chinese/special characters
- Fixed FFmpeg argument order bug causing silent failures
- Fixed stderr buffer deadlock
- Real-time progress display (0%-100%)

---

## 中文使用说明

### 这是什么工具

**批量视频配音合成工具** —— 一键完成：去除原视频音频 → 替换为翻译后的中文配音 → 烧录/嵌入中文字幕 → 缩放到目标分辨率 → HEVC 硬件编码。

专门为处理翻译后的交易教育视频而设计。

### 下载与使用

**方法一：下载 EXE（推荐）**

1. 前往 **[Releases 页面](https://github.com/cc9527-1/-BatchReplaceAudioBurnSub/releases)** 下载 `BatchReplaceAudioBurnSub.exe`
2. 双击运行（无需安装 Python）
3. 选择视频文件夹 → 点击 **Scan** 扫描文件 → 勾选需要处理的视频 → 点击 **START**

**方法二：运行源码**

```bash
python gui.py
```

需要 Python 3.7+ 和 FFmpeg 8.0+（含 hevc_amf 编码器）。

### 文件命名规则

| 文件 | 命名要求 | 示例 |
|------|---------|------|
| 视频 | 任意 `.mp4/.mkv/.mov` 文件 | `001 如何交易黄金.mp4` |
| 翻译音频 | 必须带 `_translated` / `_翻译` / `_zh` 等标记 | `001 如何交易黄金_translated.mp3` |
| 翻译字幕 | 必须带 `_translated` / `_翻译` / `_zh` 等标记 | `001 如何交易黄金_translated.srt` |

匹配规则：
1. **编号前缀匹配** —— 如果视频是 `001 xxx.mp4`，自动匹配 `001 xxx_translated.mp3`
2. **相似度匹配** —— 无编号时按文件名相似度模糊匹配

### 参数设置说明

| 参数 | 可选值 | 默认 |
|------|--------|------|
| 分辨率 | 720p / 1080p / 2K / 4K | 1080p |
| 码率 | 4M / 6M / 8M / 10M / 12M / 15M / 20M | 8M |
| RC 模式 | VBR (智能) / CBR (固定) / CQ (恒定质量) | VBR (智能) |
| 编码器 | AMD GPU (hevc_amf) / CPU (libx264) | AMD GPU |
| 并行数 | 2 / 3 / 4 / 5 / 6 | 4 |
| 人声 EQ | 无 / 清晰 / 温暖 / 去齿音 / 会议室 | 无 |

### RC 模式选哪个

| 模式 | 体积 | 画质 | 推荐场景 |
|------|------|------|---------|
| **CQ**（恒定质量） | 最小（比 CBR 小 70%） | 优秀 | 幻灯片、录屏、PPT 类内容 |
| **VBR**（智能码率） | 适中 | 最佳平衡 | 通用（推荐） |
| **CBR**（固定码率） | 最大 | 最稳定 | 直播、严格限制码率的场景 |

### 输出目录

所有压制完成的视频输出到源文件夹下的 `_video_out/` 目录：

```
你的视频文件夹/
├── 001 如何交易黄金.mp4
├── 001 如何交易黄金_translated.mp3
├── 001 如何交易黄金_translated.srt
└── _video_out/
    └── 001 如何交易黄金_1080p.mp4    ← 输出文件
```

### 系统要求

- **Windows 系统**（AMF 硬编码需要 AMD 显卡 + Windows）
- **FFmpeg 8.0+** —— 放到 `%LOCALAPPDATA%\ffmpeg\ffmpeg-8.0.1-essentials_build\bin\` 或添加到 PATH
- **AMD 显卡**（可选，没有则自动降级为 CPU 编码）

## License

MIT
