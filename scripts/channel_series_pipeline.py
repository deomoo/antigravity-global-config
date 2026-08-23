import os
import sys
import re
import json
import time
import asyncio
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional
from PIL import Image, ImageDraw, ImageFont

# Fix Windows stdout encoding
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='ignore')
        sys.stderr.reconfigure(encoding='utf-8', errors='ignore')
    except AttributeError:
        pass

try:
    import edge_tts
    HAS_EDGE_TTS = True
except ImportError:
    HAS_EDGE_TTS = False

OUTPUT_BASE_DIR = Path(r"C:\Users\deomo\channel_automation\topics")
OUTPUT_BASE_DIR.mkdir(parents=True, exist_ok=True)

# High-density domain knowledge templates for professional finance & tech
HIGH_SIGNAL_CURRICULUM_TEMPLATES = {
    "5_crypto_mistakes": [
        {
            "episode": 1,
            "badge": "CRYPTO MISTAKES | EP.01",
            "title": "2 ข้อผิดพลาดที่ทำให้พอร์ตแตก",
            "visual_points": [
                ("1. All-in เทหมดหน้าตัก", "ติดลบ -50% ต้องทำกำไร +100% ถึงจะคืนทุน!"),
                ("2. ไร้ Stop Loss", "ทนถือติดลบจนดอยยาว -> แก้ด้วย 'กฎ 2% Rule'"),
                ("สูตรมือโปร", "จำกัดความเสี่ยงไม้ละ < 2% วาง SL ใต้แนวรับ")
            ],
            "accent_color": (239, 68, 68),  # Red alert
            "hook": "คุณรู้ไหมครับว่า 90% ของมือใหม่ในตลาดคริปโต ขาดทุนหมดตัวเพราะ 2 ข้อนี้ตั้งแต่สัปดาห์แรก!",
            "content": "ข้อที่ 1: การ All-in เทหมดหน้าตักในเหรียญเดียว โดยคิดว่าจะรวยข้ามคืน จำไว้เลยครับว่าถ้าพอร์ตคุณติดลบ 50% คุณต้องทำกำไรถึง 100% เพื่อแค่กลับมาเท่าทุน! ข้อที่ 2: การไม่ยอมตั้ง Stop Loss หลายคนทนถือติดลบจนกลายเป็นดอยยาว วิธีแก้ที่มืออาชีพใช้คือ กฎ 2% Rule ห้ามเสี่ยงเกิน 2% ของพอร์ตในหนึ่งไม้ และวาง Stop Loss ใต้แนวรับสำคัญเสมอ",
            "cliffhanger": "แต่นี่ยังไม่ใช่ข้อที่อันตรายที่สุดครับ ในตอนที่ 2 เราจะมาดูข้อผิดพลาดเรื่อง Leverage ที่ดูดเงินนักเทรดไปมากที่สุด กดติดตามรอไว้เลยครับ!"
        },
        {
            "episode": 2,
            "badge": "CRYPTO MISTAKES | EP.02",
            "title": "กับดัก Leverage & FOMO ไล่ราคา",
            "visual_points": [
                ("3. Over-Leverage 20x-50x", "กราฟสวิงแค่ 2% = ล้างพอร์ตทันที (Liquidation)"),
                ("4. FOMO ไล่ซื้อแท่งเขียว", "แท่งเขียวคือจุดที่เจ้ามือเทขายทำกำไร"),
                ("สูตรมือโปร", "คุม Leverage < 5x และรอ Pullback ย่อตัวเข้าแนวรับ")
            ],
            "accent_color": (245, 158, 11),  # Orange / Amber
            "hook": "ต่อจากตอนที่แล้ว หลังจากเรารู้วิธีคุมความเสี่ยง 2% กันไปแล้ว ในตอนนี้คือหลุมพรางที่ดูดเงินเร็วที่สุดครับ!",
            "content": "ข้อที่ 3: การใช้ Leverage สูงเกินไป เช่น 20x หรือ 50x ในตลาดคริปโตที่ผันผวน กราฟสวิงผิดทางแค่ 2% พอร์ตคุณจะถูกล้างทันที (Liquidation) มือโปรจะใช้ Leverage ไม่เกิน 3x ถึง 5x เท่านั้น ข้อที่ 4: อาการ FOMO วิ่งไล่ซื้อตอนแท่งเขียวยาวๆ จำไว้ว่าเขียวคือช่วงที่เจ้ามือกำลังเทขายทำกำไร วิธีที่ถูกต้องคือ รอราคาย่อตัว (Pullback) ลงมาทดสอบแนวรับ หรือเส้น EMA ก่อนค่อยหาจังหวะเข้า",
            "cliffhanger": "แล้วข้อผิดพลาดสุดท้ายที่ร้ายแรงที่สุดและทำลายจิตวิทยานักเทรดคืออะไร? พร้อมสูตรจัดพอร์ต 50-30-20 ติดตามได้ในตอนที่ 3 ครับ!"
        },
        {
            "episode": 3,
            "badge": "CRYPTO MISTAKES | EP.03",
            "title": "Revenge Trading & สูตร 50-30-20",
            "visual_points": [
                ("5. Revenge Trading", "เทรดแก้มือด้วยอารมณ์ -> กฎแพ้ 2 ไม้พัก 24 ชม."),
                ("สูตรพอร์ต 50-30-20", "50% ถือเหรียญหลัก (BTC/ETH) รันเทรนด์"),
                ("บริหารความเสี่ยง", "30% เทรดสั้นตามระบบ | 20% สำรองเงินสดช้อนซื้อ")
            ],
            "accent_color": (16, 185, 129),  # Emerald Green
            "hook": "ในบทสรุปนี้ คือสิ่งที่แบ่งแยกระหว่างคนที่ล้มเหลว กับนักเทรด 10% ที่ทำกำไรยั่งยืนในตลาดคริปโตครับ!",
            "content": "ข้อที่ 5: Revenge Trading หรือการเทรดแก้มือด้วยอารมณ์ พอแพ้ไม้แรกแล้วรีบเบิ้ลไม้ใหญ่ขึ้นเพื่อเอาคืน ผลลัพธ์คือพอร์ตพังในวันเดียว กฎเหล็กคือ ถ้าแพ้ติดกัน 2 ไม้ ให้ปิดจอพักทันที 24 ชั่วโมง และทางรอดที่แท้จริงคือสูตรจัดพอร์ต 50-30-20: 50% ถือเหรียญหลักอย่าง Bitcoin และ Ethereum, 30% ใช้เทรดสั้นตามระบบ, และ 20% เก็บเป็นเงินสดสำรองไว้ช้อนซื้อตอนตลาด Panic",
            "cliffhanger": "ถ้านำ 5 ข้อนี้ไปปรับใช้ พอร์ตของคุณจะปลอดภัยขึ้นทันที กดบันทึกคลิปนี้ไว้ และกดติดตามช่องเพื่อรับความรู้การเทรดแบบเจาะลึกทุกวันครับ!"
        }
    ]
}

class ChannelSeriesEngine:
    def __init__(self, output_dir: Optional[Path] = None):
        self.base_dir = output_dir or OUTPUT_BASE_DIR
        self.default_voice = "th-TH-NiwatNeural"
        self.alt_voice = "th-TH-PremwadeeNeural"

    def slugify(self, text: str) -> str:
        cleaned = re.sub(r'[^\w\s-]', '', text.lower()).strip()
        slug = re.sub(r'[-\s]+', '_', cleaned)
        return slug or f"topic_{int(time.time())}"

    def plan_series(self, topic_title: str, num_episodes: int = 3, target_audience: str = "Crypto & Forex Traders") -> Dict[str, Any]:
        topic_slug = self.slugify(topic_title)
        topic_dir = self.base_dir / topic_slug
        topic_dir.mkdir(parents=True, exist_ok=True)

        episodes_plan = []
        for i in range(1, num_episodes + 1):
            if i == 1:
                phase = "Foundation & The 2 Fatal Mistakes"
                summary = "2 ข้อผิดพลาดแรก: All-in ไม่แบ่งไม้ & ไร้ Stop Loss พร้อมตัวเลขความจริงเรื่องคณิตศาสตร์การกู้พอร์ต"
            elif i == 2:
                phase = "Leverage Trap & FOMO Psychology"
                summary = "ข้อ 3 และ 4: กับดัก Leverage สูงล้างพอร์ต & อาการ FOMO ไล่ซื้อแท่งเขียว พร้อมจังหวะเข้าที่ถูกต้อง"
            else:
                phase = "Revenge Trading & 50-30-20 Portfolio Rule"
                summary = "ข้อ 5: Revenge Trading เทรดแก้มือ & สูตรจัดพอร์ตทางรอด 50-30-20"

            ep_slug = f"ep{i:02d}_{self.slugify(phase)}"
            episodes_plan.append({
                "episode_number": i,
                "phase": phase,
                "slug": ep_slug,
                "goal": summary,
                "status": "planned"
            })

        manifest = {
            "topic_title": topic_title,
            "topic_slug": topic_slug,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "target_audience": target_audience,
            "tone_of_voice": "High-Value, Analytical, Direct, Actionable Thai",
            "aspect_ratio": "9:16 (1080x1920)",
            "total_episodes": num_episodes,
            "episodes": episodes_plan
        }

        manifest_path = topic_dir / "topic_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
        print(f"[+] Created High-Value Series Manifest: {manifest_path}")
        return manifest

    def generate_substantive_script(self, topic_slug: str, episode_num: int) -> Dict[str, Any]:
        topic_dir = self.base_dir / topic_slug
        manifest_path = topic_dir / "topic_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        ep_meta = next(ep for ep in manifest["episodes"] if ep["episode_number"] == episode_num)
        
        ep_dir = topic_dir / ep_meta["slug"]
        ep_dir.mkdir(parents=True, exist_ok=True)

        curriculum = HIGH_SIGNAL_CURRICULUM_TEMPLATES.get("5_crypto_mistakes", [])
        matched_ep = next((item for item in curriculum if item["episode"] == episode_num), None)

        if matched_ep:
            hook = matched_ep["hook"]
            body = matched_ep["content"]
            cliffhanger = matched_ep["cliffhanger"]
            title = matched_ep["title"]
        else:
            hook = f"ถ้าคุณกำลังเทรด {manifest['topic_title']} และยังทำแบบนี้อยู่ พอร์ตของคุณกำลังเสี่ยงที่จะเสียหายหนักครับ!"
            body = f"สิ่งที่คุณต้องทำทันทีคือ 1. จำกัดความเสี่ยงไม่เกิน 1-2% ต่อไม้ 2. คำนวณ Risk Reward Ratio ให้มากกว่า 1:2 เสมอ และ 3. รอจังหวะการคอนเฟิร์มของสัญญาณก่อนเปิดออเดอร์"
            cliffhanger = "กดติดตามช่องไว้เพื่อรับกลยุทธ์การเทรดที่นำไปใช้สร้างกำไรได้จริงทุกวันครับ!"
            title = f"EP.{episode_num:02d} - {ep_meta['phase']}"

        full_narration = f"{hook} {body} {cliffhanger}"

        script_data = {
            "episode_number": episode_num,
            "topic_title": manifest["topic_title"],
            "episode_title": title,
            "hook": hook,
            "body_value_actionable": body,
            "cliffhanger_cta": cliffhanger,
            "full_narration": full_narration,
            "actionable_takeaway": "กฎ 2% Rule, การคุม Leverage ต่ำ, การรอ Pullback และสูตรพอร์ต 50-30-20",
            "hashtags": ["#คริปโต", "#สอนเทรด", "#เทรดคริปโต", "#ลงทุน", "#Bitcoin", "#MoneyManagement", "#Shorts"],
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }

        script_file = ep_dir / "script.json"
        script_file.write_text(json.dumps(script_data, indent=2, ensure_ascii=False), encoding='utf-8')
        print(f"[+] Saved High-Value Script for EP.{episode_num}: {script_file}")
        return script_data

    def create_visual_graphic_card(self, topic_slug: str, episode_num: int) -> Path:
        """
        Creates a high-retention, stylish 1080x1920 graphic card with dark gradient,
        badge, bold typography, glowing info boxes, and key tactical takeaways.
        """
        topic_dir = self.base_dir / topic_slug
        manifest = json.loads((topic_dir / "topic_manifest.json").read_text(encoding='utf-8'))
        ep_meta = next(ep for ep in manifest["episodes"] if ep["episode_number"] == episode_num)
        ep_dir = topic_dir / ep_meta["slug"]
        
        curriculum = HIGH_SIGNAL_CURRICULUM_TEMPLATES.get("5_crypto_mistakes", [])
        matched_ep = next((item for item in curriculum if item["episode"] == episode_num), curriculum[0])

        img = Image.new('RGB', (1080, 1920), color=(11, 15, 25))
        draw = ImageDraw.Draw(img)

        # Background Cyberpunk Gradient & Glow Rings
        accent = matched_ep.get("accent_color", (59, 130, 246))
        for r in range(400, 0, -20):
            alpha = int(15 * (1 - r / 400))
            draw.ellipse(
                [(540 - r, 300 - r), (540 + r, 300 + r)],
                fill=(accent[0]//4, accent[1]//4, accent[2]//4)
            )

        # Fonts - Try Windows standard fonts (Segoe UI, Tahoma, Arial)
        font_large = None
        font_med = None
        font_small = None
        
        for font_name in ["tahoma.ttf", "segoeui.ttf", "arial.ttf"]:
            try:
                font_large = ImageFont.truetype(font_name, 56)
                font_med = ImageFont.truetype(font_name, 40)
                font_small = ImageFont.truetype(font_name, 32)
                font_badge = ImageFont.truetype(font_name, 28)
                break
            except Exception:
                pass
                
        if not font_large:
            font_large = font_med = font_small = font_badge = ImageFont.load_default()

        # Top Badge: [🔥 BADGE]
        badge_text = f"  {matched_ep.get('badge', 'TRADING MASTERCLASS')}  "
        draw.rounded_rectangle([(140, 120), (940, 185)], radius=30, fill=(30, 41, 59), outline=accent, width=3)
        draw.text((540, 152), badge_text, fill=accent, font=font_badge, anchor="mm")

        # Main Headline
        draw.text((540, 280), "5 ข้อผิดพลาดของมือใหม่", fill=(241, 245, 249), font=font_large, anchor="mm")
        draw.text((540, 360), matched_ep.get("title", f"EP.{episode_num}"), fill=accent, font=font_med, anchor="mm")

        # Visual Info Box Container
        draw.rounded_rectangle([(80, 460), (1000, 1540)], radius=35, fill=(15, 23, 42), outline=(51, 65, 85), width=3)

        # Draw 3 Key Visual Points
        points = matched_ep.get("visual_points", [])
        y_start = 540
        for idx, (label, detail) in enumerate(points):
            # Card sub-box
            draw.rounded_rectangle([(120, y_start), (960, y_start + 280)], radius=25, fill=(2, 6, 23), outline=(30, 41, 59), width=2)
            # Label
            draw.text((160, y_start + 40), f"⚡ {label}", fill=(255, 255, 255), font=font_med)
            # Detail lines
            draw.text((160, y_start + 120), detail, fill=(148, 163, 184), font=font_small)
            y_start += 330

        # Bottom Channel Branding / CTA Bar
        draw.rounded_rectangle([(140, 1620), (940, 1720)], radius=25, fill=accent)
        draw.text((540, 1670), "🔥 กดติดตามเพื่อรับกลยุทธ์เทรดทุกวัน", fill=(255, 255, 255), font=font_med, anchor="mm")

        out_img_path = ep_dir / "visual_card.png"
        img.save(str(out_img_path), quality=95)
        print(f"[+] Generated High-Definition Graphic Card: {out_img_path}")
        return out_img_path

    async def _async_generate_voiceover(self, text: str, output_path: Path, voice: str):
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(str(output_path))

    def generate_voiceover(self, topic_slug: str, episode_num: int, voice: Optional[str] = None) -> Path:
        topic_dir = self.base_dir / topic_slug
        manifest = json.loads((topic_dir / "topic_manifest.json").read_text(encoding='utf-8'))
        ep_meta = next(ep for ep in manifest["episodes"] if ep["episode_number"] == episode_num)
        ep_dir = topic_dir / ep_meta["slug"]
        
        script = json.loads((ep_dir / "script.json").read_text(encoding='utf-8'))
        text = script["full_narration"]
        
        audio_file = ep_dir / "voiceover.mp3"
        selected_voice = voice or self.default_voice
        
        print(f"[*] Synthesizing Actionable Thai Voiceover ({selected_voice})...")
        asyncio.run(self._async_generate_voiceover(text, audio_file, selected_voice))
        print(f"[+] Voiceover Generated: {audio_file} ({audio_file.stat().st_size} bytes)")
        
        self._generate_srt(script["full_narration"], ep_dir / "subtitles.srt")
        return audio_file

    def _generate_srt(self, narration_text: str, srt_path: Path):
        sentences = [s.strip() for s in re.split(r'([.?!]+|\s{2,}|ครับ|นะครับ|เสมอ|ทันที)', narration_text) if s.strip() and not re.match(r'^[.?!]+$', s)]
        if not sentences:
            sentences = [narration_text]
            
        srt_content = []
        current_time = 0.0
        sec_per_char = 0.08
        
        for idx, sentence in enumerate(sentences, start=1):
            duration = max(1.8, len(sentence) * sec_per_char)
            start_str = self._format_srt_time(current_time)
            end_str = self._format_srt_time(current_time + duration)
            current_time += duration + 0.2
            
            srt_content.append(f"{idx}\n{start_str} --> {end_str}\n{sentence}\n")
            
        srt_path.write_text("\n".join(srt_content), encoding='utf-8')
        print(f"[+] Generated Subtitle File: {srt_path}")

    def _format_srt_time(self, seconds: float) -> str:
        hrs = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        msecs = int((seconds - int(seconds)) * 1000)
        return f"{hrs:02d}:{mins:02d}:{secs:02d},{msecs:03d}"

    def render_final_video(self, topic_slug: str, episode_num: int) -> Path:
        topic_dir = self.base_dir / topic_slug
        manifest = json.loads((topic_dir / "topic_manifest.json").read_text(encoding='utf-8'))
        ep_meta = next(ep for ep in manifest["episodes"] if ep["episode_number"] == episode_num)
        ep_dir = topic_dir / ep_meta["slug"]
        
        audio_path = ep_dir / "voiceover.mp3"
        img_path = ep_dir / "visual_card.png"
        video_out = ep_dir / "final_short_9x16.mp4"
        
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file missing: {audio_path}")
        if not img_path.exists():
            img_path = self.create_visual_graphic_card(topic_slug, episode_num)

        print(f"[*] Rendering 9:16 Vertical Video with Animated Graphic Cards & Hardware Accel...")
        
        # FFmpeg with visual image background + subtle smooth zoom animation
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", str(img_path),
            "-i", str(audio_path),
            "-vf", "scale=1080:1920,format=yuv420p",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            str(video_out)
        ]
        
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[+] [SUCCESS] Rendered Final Video with Visual Graphics: {video_out} ({video_out.stat().st_size} bytes)")
        
        ep_meta["status"] = "rendered"
        ep_meta["video_file"] = str(video_out)
        (topic_dir / "topic_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
        return video_out

    def build_full_series(self, topic_title: str, num_episodes: int = 3) -> Dict[str, Any]:
        print(f"\n========================================================")
        print(f" Building High-Retention Video Series with Visual Infographics: '{topic_title}' ({num_episodes} Episodes)")
        print(f"========================================================")
        
        manifest = self.plan_series(topic_title, num_episodes)
        topic_slug = manifest["topic_slug"]
        
        for ep in range(1, num_episodes + 1):
            print(f"\n--- Generating Episode {ep}/{num_episodes} ---")
            self.generate_substantive_script(topic_slug, ep)
            self.create_visual_graphic_card(topic_slug, ep)
            self.generate_voiceover(topic_slug, ep)
            self.render_final_video(topic_slug, ep)
            
        print(f"\n[+] High-Retention Series '{topic_title}' built successfully at: {self.base_dir / topic_slug}")
        return manifest

if __name__ == "__main__":
    engine = ChannelSeriesEngine()
    if len(sys.argv) > 1:
        title = sys.argv[1]
        eps = int(sys.argv[2]) if len(sys.argv) > 2 else 3
        engine.build_full_series(title, eps)
