import os
import time
import subprocess
import shutil
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import cv2
import numpy as np

PORT = 8998
DELIV_DIR = Path(__file__).resolve().parent

output_video_path = DELIV_DIR / "nexus_cinematic_walkthrough.mp4"
poster_path = DELIV_DIR / "nexus_video_poster.jpg"
poster_composed_path = DELIV_DIR / "nexus_video_poster_composed.jpg"

W, H = 1920, 1080
FPS = 30
TOTAL_FRAMES = 900 # 30 seconds

fourcc = cv2.VideoWriter_fourcc(*'mp4v')
out_writer = cv2.VideoWriter(str(output_video_path), fourcc, FPS, (W, H))
if not out_writer.isOpened():
    raise RuntimeError(f"Could not create output video: {output_video_path}")

frames_written = 0
done_signal = False

class FrameHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DELIV_DIR, **kwargs)

    def log_message(self, format, *args):
        # Suppress noisy HTTP request logging
        return

    def do_POST(self):
        global frames_written, done_signal
        if self.path.startswith('/upload_frame'):
            content_length = int(self.headers['Content-Length'])
            raw_bytes = self.rfile.read(content_length)

            # Decode JPEG in memory
            nparr = np.frombuffer(raw_bytes, np.uint8)
            frame_img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if frame_img is not None:
                if frame_img.shape[0] != H or frame_img.shape[1] != W:
                    frame_img = cv2.resize(frame_img, (W, H))
                out_writer.write(frame_img)

                # Save pristine poster still frame (at entrance approach ~frame 150)
                if frames_written == 150:
                    cv2.imwrite(str(poster_path), frame_img)
                    print(f"Captured video poster frame at frame {frames_written}: {poster_path}")
                elif frames_written == 880:
                    cv2.imwrite(str(poster_composed_path), frame_img)
                    print(f"Captured composed final poster at frame {frames_written}: {poster_composed_path}")

                frames_written += 1
                if frames_written % 100 == 0 or frames_written == 1:
                    print(f"Rendered {frames_written}/{TOTAL_FRAMES} frames ({frames_written/TOTAL_FRAMES*100:.1f}%)")

            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"OK")

        elif self.path.startswith('/done'):
            done_signal = True
            print("Received /done signal from WebGL renderer.")
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"DONE")
        else:
            self.send_response(404)
            self.end_headers()

def main():
    print("Starting local WebGL video render server on port", PORT)
    server = HTTPServer(('127.0.0.1', PORT), FrameHandler)
    server.timeout = 1.0

    chrome = shutil.which("chrome") or shutil.which("chrome.exe")
    if not chrome:
        chrome_candidates = [
            Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
        ]
        chrome = next((str(candidate) for candidate in chrome_candidates if candidate.is_file()), None)
    if not chrome:
        raise FileNotFoundError("Google Chrome was not found. Install Chrome or add it to PATH to render the video.")
    cmd = [
        chrome,
        "--headless=new",
        "--no-sandbox",
        "--disable-gpu",
        "--window-size=1920,1080",
        f"http://127.0.0.1:{PORT}/renderer.html"
    ]
    print("Spawning Chrome headless WebGL engine...")
    proc = subprocess.Popen(cmd)

    start_time = time.time()
    max_timeout = 360 # 6 minutes max

    try:
        while not done_signal and (time.time() - start_time) < max_timeout:
            server.handle_request()
    finally:
        out_writer.release()
        proc.terminate()
        server.server_close()

    print(f"Render completed. Total frames encoded: {frames_written}")
    if output_video_path.exists():
        size_mb = output_video_path.stat().st_size / (1024 * 1024)
        print(f"Master video produced: {output_video_path} ({size_mb:.2f} MB)")

if __name__ == "__main__":
    main()
