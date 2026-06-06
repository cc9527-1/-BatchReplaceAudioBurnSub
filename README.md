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

### Option 1: Use the pre-built EXE (recommended)

1. Download `AI视频合并工具.exe`
2. Launch it (or use `启动.bat` to hide the console window)
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

## License

MIT
