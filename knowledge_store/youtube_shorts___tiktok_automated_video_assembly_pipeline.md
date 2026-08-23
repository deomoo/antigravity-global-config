# Knowledge Profile: YouTube Shorts & TikTok Automated Video Assembly Pipeline
- **Domain**: Channel & Media Automation
- **Harvested Date**: 2026-08-16 13:03:15
- **Keywords**: moviepy, ffmpeg, whisper subtitles, edge-tts, auto-rendering, reels automation

### [Channel Automation] Headless Short-Form Video Generation Pipeline
- **Core Architecture**: Python headless video compilation combining script generation (LLM) -> Voiceover (Edge-TTS / Kokoro) -> Subtitle Generation (Whisper word-level timestamps) -> Video Assembly (`moviepy` / `ffmpeg-python`).
- **Key Technique**:
  1. Generate SRT subtitle tracks with word-level highlighting (Karaoke effect).
  2. Overlay 9:16 background gameplay / b-roll video with dynamic zoom & pan (Ken Burns effect).
  3. Batch render directly via hardware acceleration (`h264_nvenc` on GTX 1060).
- **Production Code Pattern**:
```python
import edge_tts
import asyncio
import subprocess

async def generate_voiceover(text, output_mp3, voice="th-TH-NiwatNeural"):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_mp3)

def render_shorts_ffmpeg(video_in, audio_in, srt_in, video_out):
    cmd = [
        "ffmpeg", "-y",
        "-i", video_in, "-i", audio_in,
        "-vf", f"crop=ih*(9/16):ih,subtitles={srt_in}:force_style='FontSize=24,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=3'",
        "-c:v", "h264_nvenc", "-preset", "fast",
        "-c:a", "aac", "-shortest", video_out
    ]
    subprocess.run(cmd, check=True)
```
- **Actionable Application**: Use this template to auto-produce automated educational and market recap shorts for YouTube and TikTok without manual editing.