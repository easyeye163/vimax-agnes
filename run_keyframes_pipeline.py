#!/usr/bin/env python3
"""Keyframes pipeline runner: generates all scenes with keyframes chaining.

Scene N's end_frame image becomes Scene N+1's first_frame, giving zero-jump
transitions. Uses extra_body format for keyframes mode on Agnes video API.

Features:
  - State persistence (resume after crash/restart)
  - Automatic retry with exponential backoff for 429 (rate limit)
  - Separate submit and poll phases for long-running tasks
  - Video concatenation via moviepy
"""

import json
import requests
import time
import os
import base64
import mimetypes
import shutil

API_KEY = "sk-IpvltJlHQGKTxzwGn0Eg0tfrscrBVMKrdjdmWc5bofC2DUP0"
BASE_URL = "https://apihub.agnes-ai.com/v1"
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
WORK_DIR = ".working_dir/idea2video"
STATE_FILE = os.path.join(WORK_DIR, "kf_state.json")
LOG_FILE = os.path.join(WORK_DIR, "kf_log.txt")
W, H, NF, FR = 768, 1152, 241, 24
MAX_RETRIES = 5
RETRY_BASE = 60  # seconds


def log(msg):
    print(msg, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(s):
    with open(STATE_FILE, "w") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)


def upload_img(path):
    """Upload a local image to get a hosted URL via img2img API."""
    for attempt in range(MAX_RETRIES):
        try:
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            mime = mimetypes.guess_type(path)[0] or "image/png"
            uri = f"data:{mime};base64,{b64}"
            resp = requests.post(f"{BASE_URL}/images/generations", headers=HEADERS, json={
                "model": "agnes-image-2.1-flash", "prompt": "exact same image",
                "n": 1, "size": "1024x1024",
                "extra_body": {"response_format": "url", "image": uri}
            }, timeout=180)
            if resp.status_code == 429:
                delay = 30 * (attempt + 1)
                log(f"  Upload 429, retry in {delay}s...")
                time.sleep(delay)
                continue
            resp.raise_for_status()
            url = resp.json()["data"][0]["url"]
            log(f"  Uploaded: {url[:60]}...")
            return url
        except Exception as e:
            log(f"  Upload attempt {attempt+1} failed: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(15)
    raise RuntimeError(f"Failed to upload image after {MAX_RETRIES} retries")


def upload_url(url):
    """Upload a URL-based image to get a fresh hosted URL."""
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(f"{BASE_URL}/images/generations", headers=HEADERS, json={
                "model": "agnes-image-2.1-flash", "prompt": "exact same image",
                "n": 1, "size": "1024x1024",
                "extra_body": {"response_format": "url", "image": url}
            }, timeout=180)
            if resp.status_code == 429:
                delay = 30 * (attempt + 1)
                log(f"  Re-host 429, retry in {delay}s...")
                time.sleep(delay)
                continue
            resp.raise_for_status()
            url2 = resp.json()["data"][0]["url"]
            log(f"  Re-hosted: {url2[:60]}...")
            return url2
        except Exception as e:
            log(f"  Re-host attempt {attempt+1} failed: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(15)
    raise RuntimeError(f"Failed to re-host image after {MAX_RETRIES} retries")


def gen_t2i(prompt, size):
    """Generate image via text-to-image API with retry."""
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(f"{BASE_URL}/images/generations", headers=HEADERS, json={
                "model": "agnes-image-2.1-flash", "prompt": prompt,
                "n": 1, "size": size
            }, timeout=120)
            if resp.status_code == 429:
                delay = 30 * (attempt + 1)
                log(f"  T2I 429, retry in {delay}s...")
                time.sleep(delay)
                continue
            resp.raise_for_status()
            return resp.json()["data"][0].get("url", "")
        except Exception as e:
            log(f"  T2I attempt {attempt+1} failed: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(15)
    raise RuntimeError(f"Failed to generate image after {MAX_RETRIES} retries")


def download(url, path):
    resp = requests.get(url, timeout=300, stream=True)
    with open(path, "wb") as f:
        for chunk in resp.iter_content(8192):
            f.write(chunk)
    sz = os.path.getsize(path)
    log(f"  Downloaded: {path} ({sz//1024}KB)")
    return sz


def submit_keyframes(prompt, img_urls, w=W, h=H):
    """Submit a keyframes video task with retry for 429/5xx errors.

    Keyframes format: extra_body with image list and mode.
    """
    payload = {
        "model": "agnes-video-v2.0",
        "prompt": prompt,
        "width": w, "height": h,
        "num_frames": NF, "frame_rate": FR,
        "extra_body": {
            "image": img_urls,
            "mode": "keyframes",
        }
    }

    for attempt in range(MAX_RETRIES):
        try:
            log(f"  Submitting keyframes video (attempt {attempt+1})...")
            resp = requests.post(f"{BASE_URL}/videos", headers=HEADERS, json=payload, timeout=120)

            if resp.status_code == 200:
                result = resp.json()
                tid = result.get("task_id") or result.get("id")
                log(f"  Task: {tid[:30]}...")
                return tid

            if resp.status_code == 429:
                delay = RETRY_BASE * (attempt + 1)
                log(f"  429 rate limit, retry in {delay}s...")
                time.sleep(delay)
                continue

            if resp.status_code >= 500:
                delay = RETRY_BASE * (attempt + 1)
                log(f"  {resp.status_code} server error, retry in {delay}s...")
                time.sleep(delay)
                continue

            # Other errors — don't retry
            log(f"  HTTP {resp.status_code}: {resp.text[:300]}")
            raise RuntimeError(f"Video submit failed: HTTP {resp.status_code}")

        except requests.exceptions.Timeout:
            delay = RETRY_BASE * (attempt + 1)
            log(f"  Timeout, retry in {delay}s...")
            time.sleep(delay)
            continue

    raise RuntimeError(f"Video submit failed after {MAX_RETRIES} retries")


def poll(tid, max_wait=600):
    """Poll a video task until completed or failed."""
    deadline = time.time() + max_wait
    last_status = ""
    while time.time() < deadline:
        try:
            resp = requests.get(f"{BASE_URL}/videos/{tid}", headers=HEADERS, timeout=15)
            d = resp.json()
            st = d.get("status", "")
            pr = d.get("progress", 0)

            if st != last_status:
                log(f"  ... {st} {pr}%")
                last_status = st

            if st in ("completed", "COMPLETED"):
                url = d.get("video_url") or d.get("url") or d.get("remixed_from_video_id")
                log(f"  Completed! URL: {url[:80]}...")
                return url

            if st in ("failed", "FAILED"):
                err = d.get("error") or "unknown"
                raise RuntimeError(f"Video failed: {err}")

        except RuntimeError:
            raise
        except Exception as e:
            log(f"  Poll err: {e}")

        time.sleep(20)

    raise TimeoutError(f"Video task timed out after {max_wait}s")


def main():
    os.makedirs(WORK_DIR, exist_ok=True)
    state = load_state()

    with open(os.path.join(WORK_DIR, "script.json")) as f:
        scenes = json.load(f)
    with open(os.path.join(WORK_DIR, "end_frame_prompts.json")) as f:
        end_frames = json.load(f)

    ref_img = "/home/z/my-project/upload/weixin-image.jpg"

    # Upload reference image once
    if not state.get("ref_uploaded_url"):
        log("Uploading reference image...")
        state["ref_uploaded_url"] = upload_img(ref_img)
        save_state(state)

    current_first_frame_url = state.get("ref_uploaded_url")

    for scene_idx in range(len(scenes)):
        scene_dir = os.path.join(WORK_DIR, f"scene_{scene_idx}")
        os.makedirs(scene_dir, exist_ok=True)
        video_path = os.path.join(scene_dir, "video.mp4")

        # Skip completed scenes
        if os.path.exists(video_path) and os.path.getsize(video_path) > 10000:
            log(f"Scene {scene_idx} exists, skip.")
            ef_path = os.path.join(scene_dir, "end_frame.png")
            if os.path.exists(ef_path):
                current_first_frame_url = state.get(f"scene{scene_idx}_end_frame_hosted", current_first_frame_url)
            continue

        log(f"\n{'='*50}")
        log(f"SCENE {scene_idx} (keyframes)")
        log(f"{'='*50}")

        # Generate end frame image
        ef_path = os.path.join(scene_dir, "end_frame.png")
        if not os.path.exists(ef_path) or os.path.getsize(ef_path) < 1000:
            log(f"  Generating end frame image...")
            ef_url = gen_t2i(end_frames[scene_idx], f"{W}x{H}")
            download(ef_url, ef_path)

        # Upload end frame to hosted URL
        if not state.get(f"scene{scene_idx}_end_frame_hosted"):
            log(f"  Uploading end frame...")
            state[f"scene{scene_idx}_end_frame_hosted"] = upload_img(ef_path)
            save_state(state)
        ef_hosted = state[f"scene{scene_idx}_end_frame_hosted"]

        # Check for existing task (resume support)
        existing_tid = state.get(f"scene{scene_idx}_task_id")
        if existing_tid:
            log(f"  Checking existing task: {existing_tid[:30]}...")
            try:
                r = requests.get(f"{BASE_URL}/videos/{existing_tid}", headers=HEADERS, timeout=15)
                d = r.json()
                st = d.get("status", "")
                if st in ("completed", "COMPLETED"):
                    vurl = d.get("video_url") or d.get("url") or d.get("remixed_from_video_id")
                    download(vurl, video_path)
                    state[f"scene{scene_idx}_url"] = vurl
                    save_state(state)
                    current_first_frame_url = ef_hosted
                    continue
                elif st in ("failed", "FAILED"):
                    log(f"  Task failed ({d.get('error','unknown')}), resubmitting...")
                    existing_tid = None
                elif st == "queued":
                    # Still queued — try waiting a bit more
                    log(f"  Still queued, waiting...")
                    try:
                        vurl = poll(existing_tid, max_wait=300)
                        download(vurl, video_path)
                        state[f"scene{scene_idx}_url"] = vurl
                        save_state(state)
                        current_first_frame_url = ef_hosted
                        continue
                    except (TimeoutError, RuntimeError):
                        log(f"  Timed out/failed, resubmitting...")
                        existing_tid = None
                else:
                    log(f"  Still {st}, polling...")
                    vurl = poll(existing_tid)
                    download(vurl, video_path)
                    state[f"scene{scene_idx}_url"] = vurl
                    save_state(state)
                    current_first_frame_url = ef_hosted
                    continue
            except Exception as e:
                log(f"  Error checking task: {e}")
                existing_tid = None

        # Submit keyframes video
        log(f"  First frame: {current_first_frame_url[:60]}...")
        log(f"  End frame: {ef_hosted[:60]}...")
        tid = submit_keyframes(scenes[scene_idx], [current_first_frame_url, ef_hosted])
        state[f"scene{scene_idx}_task_id"] = tid
        save_state(state)

        # Poll until done
        vurl = poll(tid)
        download(vurl, video_path)
        state[f"scene{scene_idx}_url"] = vurl
        save_state(state)

        # Use this scene's end_frame as next scene's first_frame
        current_first_frame_url = ef_hosted

    # Concatenate
    video_paths = []
    for i in range(len(scenes)):
        vp = os.path.join(WORK_DIR, f"scene_{i}", "video.mp4")
        if os.path.exists(vp) and os.path.getsize(vp) > 10000:
            video_paths.append(vp)

    if len(video_paths) < len(scenes):
        log(f"WARNING: Only {len(video_paths)}/{len(scenes)} scenes completed")

    final = os.path.join(WORK_DIR, "final_video_kf.mp4")
    if not os.path.exists(final) or os.path.getsize(final) < 10000:
        if video_paths:
            log(f"Concatenating {len(video_paths)} videos...")
            from moviepy import VideoFileClip, concatenate_videoclips
            clips = [VideoFileClip(p) for p in video_paths]
            fc = concatenate_videoclips(clips, method="compose")
            fc.write_videofile(final, logger="bar")
            for c in clips:
                c.close()
        else:
            log("ERROR: No videos to concatenate!")
            return

    dl = "/home/z/my-project/download/singing_dancing_keyframes.mp4"
    shutil.copy2(final, dl)
    log(f"\n🎉 ALL DONE! Final: {dl}")
    state["final_video"] = dl
    state["completed"] = True
    save_state(state)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"ERROR: {e}")
        import traceback
        log(traceback.format_exc())
