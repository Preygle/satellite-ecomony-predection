from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from urbanintel.city import catalog  # noqa: E402
from urbanintel.city.progress import read_status  # noqa: E402

TABS = ["Overview", "Urban growth", "Economic activity", "News & developments",
        "Expansion opportunities", "Method & data"]


def parse(argv=None):
    ap = argparse.ArgumentParser(description="Record a timestamped timelapse of a full dashboard run.")
    ap.add_argument("--city", required=True)
    ap.add_argument("--interval", type=float, default=3.0, help="seconds between frames")
    ap.add_argument("--fps", type=int, default=12)
    ap.add_argument("--port", type=int, default=8601)
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--height", type=int, default=1000)
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--no-news", action="store_true")
    ap.add_argument("--out", default=None)
    return ap.parse_args(argv)


def wait_port(port: int, timeout: float = 90) -> None:
    t = time.time()
    while time.time() - t < timeout:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.5)
    raise RuntimeError(f"dashboard did not start on port {port}")


def font(size: int):
    for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def stamp(src: Path, dst: Path, *, city: str, wall: datetime, elapsed: float, stage: str, speed: float) -> None:
    img = Image.open(src).convert("RGB")
    bar = 46
    out = Image.new("RGB", (img.width, img.height + bar), "#0b0b0b")
    out.paste(img, (0, bar))
    d = ImageDraw.Draw(out)
    e = int(elapsed)
    left = f"{city}  |  end-to-end run  |  {stage}"
    right = (f"{wall:%Y-%m-%d %H:%M:%S}   elapsed {e // 3600:d}:{e % 3600 // 60:02d}:{e % 60:02d}"
             f"   timelapse x{speed:.0f}")
    f = font(20)
    d.text((16, 11), left, fill="#f0efec", font=f)
    w = d.textlength(right, font=f)
    d.text((img.width - w - 16, 11), right, fill="#86b6ef", font=f)
    out.save(dst, optimize=False)


def main(argv=None) -> int:
    a = parse(argv)
    from playwright.sync_api import sync_playwright

    city = catalog.resolve(a.city)
    cdir = catalog.city_dir(city)
    stamp_id = time.strftime("%Y%m%d-%H%M%S")
    work = cdir / "demo" / f"frames_{stamp_id}"
    work.mkdir(parents=True, exist_ok=True)
    out = Path(a.out) if a.out else cdir / "demo" / f"{city.slug}_run_timelapse_{stamp_id}.mp4"
    server = subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(ROOT / "dashboard" / "final_app.py"),
                               "--server.port", str(a.port), "--server.headless", "true",
                               "--browser.gatherUsageStats", "false"], cwd=str(ROOT),
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    chapters: list[tuple[float, int, str]] = []
    frames = 0
    t0 = time.time()
    speed = a.interval * a.fps
    try:
        wait_port(a.port)
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            page = browser.new_page(viewport={"width": a.width, "height": a.height})
            page.goto(f"http://localhost:{a.port}", wait_until="networkidle")
            page.get_by_text("Model seeds").wait_for(timeout=60_000)

            def snap(stage: str, hold: int = 1):
                nonlocal frames
                raw = work / "raw.png"
                page.screenshot(path=str(raw))
                for _ in range(hold):
                    frames += 1
                    stamp(raw, work / f"f_{frames:05d}.png", city=city.name, wall=datetime.now(),
                          elapsed=time.time() - t0, stage=stage, speed=speed)

            box = page.locator("[data-testid='stSelectbox']").first
            box.click()
            page.keyboard.type(city.name if city.name in catalog.CITIES else "Other")
            page.keyboard.press("Enter")
            page.wait_for_timeout(2500)
            if a.seeds != 5:
                slider = page.locator("[data-testid='stSlider'] [role='slider']").first
                slider.focus()
                for _ in range(5 - a.seeds):
                    page.keyboard.press("ArrowLeft")
            if a.no_news:
                page.get_by_text("Development news", exact=True).click()
            page.wait_for_timeout(1500)
            snap("selecting the city", hold=a.fps * 2)
            page.get_by_role("button", name="Run", exact=True).click()
            page.wait_for_timeout(4000)
            last = None
            while True:
                s = read_status(cdir / "status.json") or {}
                cur = next((x["label"] for x in s.get("stages", []) if x["state"] == "running"), None)
                label = cur or s.get("state", "starting")
                if cur and cur != last:
                    chapters.append((time.time() - t0, frames, cur))
                    last = cur
                snap(label)
                if s.get("state") in ("done", "failed") and s.get("run_id"):
                    break
                time.sleep(max(0.0, a.interval - 0.4))
            chapters.append((time.time() - t0, frames, "Results"))
            page.wait_for_timeout(6000)
            snap("results", hold=a.fps * 3)
            for tab in TABS:
                try:
                    page.get_by_role("tab", name=tab).click()
                    page.wait_for_timeout(5000)
                    page.mouse.wheel(0, 650)
                    page.wait_for_timeout(1500)
                    snap(f"results: {tab}", hold=a.fps * 3)
                    page.mouse.wheel(0, -650)
                except Exception:  # noqa: BLE001
                    continue
            browser.close()
    finally:
        server.terminate()
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-framerate", str(a.fps),
                    "-i", str(work / "f_%05d.png"), "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "24", str(out)], check=True)
    lines = [f"{city.name} end-to-end run, recorded {datetime.fromtimestamp(t0):%Y-%m-%d %H:%M}",
             f"timelapse x{speed:.0f} ({a.interval:g} s per frame at {a.fps} fps)", ""]
    for sec, frame_no, label in chapters:
        v = frame_no / a.fps
        lines.append(f"{int(v // 60):02d}:{int(v % 60):02d} in the video   "
                     f"(+{int(sec // 60):d} min {int(sec % 60):02d} s real time)   {label}")
    out.with_suffix(".chapters.txt").write_text("\n".join(lines), encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)
    s = read_status(cdir / "status.json") or {}
    print(json.dumps({"video": str(out), "frames": frames, "state": s.get("state"),
                      "real_minutes": round((time.time() - t0) / 60, 1)}, indent=1))
    return 0 if s.get("state") == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
