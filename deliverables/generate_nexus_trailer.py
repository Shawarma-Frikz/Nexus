import argparse
import math
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

def get_font(size, bold=False):
    font_path = "C:\\Windows\\Fonts\\arialbd.ttf" if bold else "C:\\Windows\\Fonts\\arial.ttf"
    try:
        return ImageFont.truetype(font_path, size)
    except Exception:
        return ImageFont.load_default()

def get_mono_font(size):
    try:
        return ImageFont.truetype("C:\\Windows\\Fonts\\consola.ttf", size)
    except Exception:
        return get_font(size)

def main():
    parser = argparse.ArgumentParser(description="Create the NEXUS intro trailer from a source screen recording.")
    parser.add_argument("source_video", type=Path, help="Path to the source screen recording")
    parser.add_argument("--output", type=Path, help="Output MP4 path (defaults to deliverables/nexus_intro_trailer.mp4)")
    args = parser.parse_args()
    source_video_path = args.source_video.expanduser().resolve()
    output_video_path = (args.output or Path(__file__).resolve().with_name("nexus_intro_trailer.mp4")).expanduser().resolve()
    output_video_path.parent.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(source_video_path))
    if not cap.isOpened():
        print("Error: Could not open source video.")
        return

    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    src_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"Source: {src_total} frames, {src_fps} fps")

    # Read key frames into a cache for smooth lookup
    # We want a 42-second high-energy trailer (1260 frames @ 30 fps)
    W, H = 1280, 720
    FPS = 30
    TOTAL_FRAMES = 1260 # 42 seconds

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(str(output_video_path), fourcc, FPS, (W, H))
    if not out.isOpened():
        cap.release()
        raise RuntimeError(f"Could not create output video: {output_video_path}")

    font_huge = get_font(52, bold=True)
    font_large = get_font(32, bold=True)
    font_med = get_font(22, bold=True)
    font_small = get_font(16, bold=False)
    font_tiny = get_font(13, bold=False)
    font_mono = get_mono_font(14)
    font_mono_small = get_mono_font(12)

    # Color definitions (BGR for OpenCV, RGB for PIL)
    CYAN_RGB = (77, 224, 199)
    CYAN_BGR = (199, 224, 77)
    BLUE_RGB = (94, 181, 247)
    BLUE_BGR = (247, 181, 94)
    EMERALD_RGB = (74, 222, 128)
    WHITE_RGB = (245, 250, 255)
    DARK_BG_RGB = (10, 22, 34)

    # Pre-read source frames mapped by second
    print("Preloading sample video frames...")
    source_cache = {}
    for frame_idx in range(0, src_total, 2):
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, f = cap.read()
        if ret:
            source_cache[frame_idx] = cv2.resize(f, (W, H))
    cap.release()
    print(f"Cached {len(source_cache)} frames.")

    def get_source_frame(target_src_idx):
        idx = max(0, min(src_total - 2, int(target_src_idx)))
        even_idx = (idx // 2) * 2
        return source_cache.get(even_idx, None)

    for i in range(TOTAL_FRAMES):
        t = i / FPS
        # Determine current act
        # Act 0: 0.0s - 3.5s (Frames 0 - 105): Intro title reveal
        # Act 1: 3.5s - 10.0s (Frames 105 - 300): Campus Overview
        # Act 2: 10.0s - 18.0s (Frames 300 - 540): NEXUS Facility & Entry
        # Act 3: 18.0s - 26.5s (Frames 540 - 795): Chemistry Lab 02
        # Act 4: 26.5s - 34.5s (Frames 795 - 1035): Classroom 01 & Attendance
        # Act 5: 34.5s - 38.5s (Frames 1035 - 1155): Room Explorer Split-Floor
        # Act 6: 38.5s - 42.0s (Frames 1155 - 1260): Outro CTA

        # Base frame setup
        if i < 105:
            # Intro Title Card
            frame = np.zeros((H, W, 3), dtype=np.uint8)
            # Subtle gradient and cyber grid
            for y_line in range(0, H, 40):
                alpha = 0.15 + 0.05 * math.sin(t * 2 + y_line * 0.05)
                cv2.line(frame, (0, y_line), (W, y_line), (int(45 * alpha), int(65 * alpha), int(30 * alpha)), 1)
            for x_line in range(0, W, 40):
                alpha = 0.15 + 0.05 * math.cos(t * 2 + x_line * 0.05)
                cv2.line(frame, (x_line, 0), (x_line, H), (int(45 * alpha), int(65 * alpha), int(30 * alpha)), 1)

            # Central pulse circle
            radius = int(80 + (t * 50) % 180)
            circle_alpha = max(0.0, 1.0 - (radius - 80) / 180.0)
            cv2.circle(frame, (W // 2, H // 2 - 20), radius, (int(199 * circle_alpha), int(224 * circle_alpha), int(77 * circle_alpha)), 1)

            img_pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            draw = ImageDraw.Draw(img_pil)

            # Logo & Titles
            fade_in = min(1.0, t / 1.2)
            title_text = "NEXUS."
            bbox = draw.textbbox((0, 0), title_text, font=font_huge)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            tx = (W - tw) // 2
            ty = H // 2 - 80
            draw.text((tx, ty), title_text, font=font_huge, fill=(245, 250, 255))
            draw.text((tx + tw - 12, ty), ".", font=font_huge, fill=CYAN_RGB)

            sub_text = "BUILDING INTELLIGENCE"
            bbox_s = draw.textbbox((0, 0), sub_text, font=font_med)
            sw = bbox_s[2] - bbox_s[0]
            draw.text(((W - sw) // 2, ty + 70), sub_text, font=font_med, fill=CYAN_RGB)

            quote_text = "WHEN EVERY ROOM HAS A VOICE, THE BUILDING MAKES SENSE."
            bbox_q = draw.textbbox((0, 0), quote_text, font=font_small)
            qw = bbox_q[2] - bbox_q[0]
            draw.text(((W - qw) // 2, ty + 125), quote_text, font=font_small, fill=(160, 185, 205))

            # Loading / system status bar
            bar_w = 320
            bar_x = (W - bar_w) // 2
            bar_y = ty + 180
            draw.rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + 4], fill=(25, 45, 65))
            fill_pct = min(1.0, t / 3.0)
            draw.rectangle([bar_x, bar_y, bar_x + int(bar_w * fill_pct), bar_y + 4], fill=CYAN_RGB)
            draw.text((bar_x, bar_y + 12), f"INITIALIZING SPATIAL TWIN // 100% NOMINAL", font=font_mono_small, fill=(120, 160, 190))

            frame = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)

        elif i >= 1155:
            # Outro CTA Card
            out_t = (i - 1155) / FPS
            frame = np.zeros((H, W, 3), dtype=np.uint8)
            # Animated hex grid accents
            for x in range(100, W, 200):
                alpha = 0.2 + 0.1 * math.sin(out_t * 3 + x)
                cv2.line(frame, (x, 0), (x, H), (int(50 * alpha), int(70 * alpha), int(35 * alpha)), 1)

            img_pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            draw = ImageDraw.Draw(img_pil)

            ty = H // 2 - 100
            draw.text(((W - 220) // 2, ty), "NEXUS.", font=font_huge, fill=(245, 250, 255))
            draw.text(((W - 320) // 2, ty + 70), "BUILDING INTELLIGENCE", font=font_med, fill=CYAN_RGB)
            draw.text(((W - 480) // 2, ty + 120), "Data from the building. Context for the people in it.", font=font_small, fill=(180, 205, 225))

            # CTA Pill Button
            btn_w, btn_h = 360, 48
            btn_x = (W - btn_w) // 2
            btn_y = ty + 175
            draw.rounded_rectangle([btn_x, btn_y, btn_x + btn_w, btn_y + btn_h], radius=10, fill=(18, 52, 78), outline=CYAN_RGB, width=2)
            btn_text = "EXPLORE THE INTERACTIVE DEMO"
            b_box = draw.textbbox((0, 0), btn_text, font=font_small)
            bw = b_box[2] - b_box[0]
            draw.text((btn_x + (btn_w - bw) // 2, btn_y + 14), btn_text, font=font_small, fill=(255, 255, 255))

            draw.text(((W - 380) // 2, ty + 245), "PROTOTYPE SYSTEM // TUNIS CONCEPT CAMPUS · 2026", font=font_mono_small, fill=(110, 145, 175))

            frame = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)

        else:
            # Active footage acts
            if i < 300:
                # Act 1: Campus
                src_target = 30 + ((i - 105) / (300 - 105)) * 180
                act_num = "01 / 04"
                act_tag = "CAMPUS SCALE · SPATIAL CONTEXT"
                act_title = "THE BIGGER PICTURE"
                act_desc = "Unified spatial telemetry connecting campus architecture to real-time events."
                pin_label = "NEXUS FACILITY · CONNECTED CAMPUS"
                pin_pos = (740, 360)
            elif i < 540:
                # Act 2: Building
                src_target = 220 + ((i - 300) / (540 - 300)) * 260
                act_num = "02 / 04"
                act_tag = "FACILITY ENVELOPE · 3 FLOORS"
                act_title = "ARCHITECTURAL RESOLUTION"
                act_desc = "Navigating from building exterior through the atrium into occupied spaces."
                pin_label = "MAIN ENTRANCE & ATRIUM LIGHTWELL"
                pin_pos = (680, 420)
            elif i < 795:
                # Act 3: Chemistry Lab
                src_target = 560 + ((i - 540) / (795 - 540)) * 340
                act_num = "03 / 04"
                act_tag = "WORKING DEMO · CHEMISTRY LAB 02"
                act_title = "HIGH-STAKES SAFETY"
                act_desc = "VAV fume hood airflow, gas readings & temperature mapped to reviewed camera events."
                pin_label = "CHEMISTRY LAB 02 // VAV AIRFLOW: 0.52 m/s"
                pin_pos = (780, 320)
            elif i < 1035:
                # Act 4: Classroom
                src_target = 940 + ((i - 795) / (1035 - 795)) * 240
                act_num = "04 / 04"
                act_tag = "WORKING DEMO · CLASSROOM 01"
                act_title = "PURPOSE-AWARE ATTENDANCE"
                act_desc = "Strict privacy separation: class attendance workflows distinct from surveillance."
                pin_label = "CLASSROOM 01 // 24/26 VERIFIED (92%)"
                pin_pos = (720, 340)
            else:
                # Act 5: Room Explorer
                src_target = 1200 + ((i - 1035) / (1155 - 1035)) * 95
                act_num = "SYSTEM"
                act_tag = "INTERACTIVE DIGITAL TWIN"
                act_title = "OPERATOR SITUATIONAL AWARENESS"
                act_desc = "Split-floor 3D building model with real-time room health status."
                pin_label = "ROOM EXPLORER // SPLIT FLOORS ACTIVE"
                pin_pos = (760, 380)

            raw_frame = get_source_frame(src_target)
            if raw_frame is not None:
                frame = raw_frame.copy()
            else:
                frame = np.zeros((H, W, 3), dtype=np.uint8)

            # Apply cinematic letterboxing (2.35:1 aspect ratio bars)
            bar_h = 48
            cv2.rectangle(frame, (0, 0), (W, bar_h), (8, 18, 28), -1)
            cv2.rectangle(frame, (0, H - bar_h), (W, H), (8, 18, 28), -1)
            cv2.line(frame, (0, bar_h), (W, bar_h), CYAN_BGR, 1)
            cv2.line(frame, (0, H - bar_h), (W, H - bar_h), CYAN_BGR, 1)

            # Floating HUD targeting reticle over key object
            px, py = pin_pos
            pulse = math.sin(t * 6) * 4
            cv2.drawMarker(frame, (px, py), CYAN_BGR, cv2.MARKER_CROSS, int(18 + pulse), 2)
            cv2.rectangle(frame, (px - 25, py - 25), (px + 25, py + 25), (int(CYAN_BGR[0] * 0.6), int(CYAN_BGR[1] * 0.6), int(CYAN_BGR[2] * 0.6)), 1)
            cv2.line(frame, (px + 25, py), (px + 90, py - 30), CYAN_BGR, 1)
            cv2.line(frame, (px + 90, py - 30), (px + 280, py - 30), CYAN_BGR, 1)

            # Convert to PIL for sharp typographic HUD overlays
            img_pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            draw = ImageDraw.Draw(img_pil)

            # Pin text
            draw.text((px + 95, py - 52), pin_label, font=font_mono, fill=CYAN_RGB)

            # Top Header Bar info
            draw.text((28, 14), "NEXUS // DIGITAL TWIN PROMOTION", font=font_mono, fill=(180, 210, 230))
            draw.text((W - 320, 14), f"TIMECODE: 00:{int(t):02d}:{int((t%1)*30):02d} · 30 FPS", font=font_mono, fill=CYAN_RGB)

            # Bottom Left Cinematic Lower-Third Card
            card_x = 36
            card_y = H - 190
            card_w = 440
            card_h = 130
            # Semi-transparent dark backing
            draw.rounded_rectangle([card_x, card_y, card_x + card_w, card_y + card_h], radius=8, fill=(10, 24, 38))
            draw.rounded_rectangle([card_x, card_y, card_x + card_w, card_y + card_h], radius=8, outline=CYAN_RGB, width=1)

            # Card typography
            draw.text((card_x + 18, card_y + 14), f"{act_num} · {act_tag}", font=font_tiny, fill=CYAN_RGB)
            draw.text((card_x + 18, card_y + 36), act_title, font=font_large, fill=WHITE_RGB)
            draw.text((card_x + 18, card_y + 78), act_desc, font=font_tiny, fill=(175, 198, 218))

            # Bottom Bar Progress
            prog_pct = min(1.0, (i - 105) / (1155 - 105))
            draw.rectangle([0, H - 4, int(W * prog_pct), H], fill=CYAN_RGB)

            # Status sensor telemetry cards on the right side
            right_card_x = W - 260
            right_card_y = H - 190
            draw.rounded_rectangle([right_card_x, right_card_y, right_card_x + 230, right_card_y + 130], radius=8, fill=(10, 24, 38), outline=(60, 95, 125), width=1)
            draw.text((right_card_x + 16, right_card_y + 14), "LIVE TELEMETRY", font=font_tiny, fill=CYAN_RGB)
            draw.text((right_card_x + 16, right_card_y + 36), "TEMP: 21.6°C", font=font_mono, fill=WHITE_RGB)
            draw.text((right_card_x + 16, right_card_y + 58), "AIR: 0.52 m/s", font=font_mono, fill=WHITE_RGB)
            draw.text((right_card_x + 16, right_card_y + 80), "VOC: 12 PPM", font=font_mono, fill=EMERALD_RGB)
            draw.text((right_card_x + 16, right_card_y + 102), "STATUS: OPTIMAL", font=font_mono_small, fill=CYAN_RGB)

            frame = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)

        out.write(frame)
        if i % 150 == 0:
            print(f"Rendered {i}/{TOTAL_FRAMES} frames ({i/TOTAL_FRAMES*100:.1f}%)")

    out.release()
    print("Video rendered successfully to:", output_video_path)


if __name__ == "__main__":
    main()
