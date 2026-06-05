#!/usr/bin/env python3
"""Background script to run the full vimax pipeline for singing/dancing video.
Polls for video completion, chains scenes, and concatenates final result.
"""

import json
import os
import requests
import time
import subprocess
import base64
import mimetypes
import shutil
import sys

API_KEY = "sk-IpvltJlHQGKTxzwGn0Eg0tfrscrBVMKrdjdmWc5bofC2DUP0"
BASE_URL = "https://apihub.agnes-ai.com/v1"
HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

WORK_DIR = ".working_dir/idea2video"
STATE_FILE = os.path.join(WORK_DIR, "task_state.json")
LOG_FILE = os.path.join(WORK_DIR, "pipeline_log.txt")

# Video params
VIDEO_WIDTH = 768
VIDEO_HEIGHT = 1152
VIDEO_DURATION = 10
NUM_FRAMES = 241
FRAME_RATE = 24


def log(msg):
    print(msg, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def upload_image_to_url(image_path):
    """Upload local image via img2img API to get hosted URL."""
    log(f"Uploading image: {image_path}")
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    mime = mimetypes.guess_type(image_path)[0] or "image/png"
    b64_uri = f"data:{mime};base64,{b64}"

    resp = requests.post(
        f"{BASE_URL}/images/generations",
        headers=HEADERS,
        json={
            "model": "agnes-image-2.1-flash",
            "prompt": "Keep the image exactly as it is",
            "n": 1,
            "size": "1024x1024",
            "extra_body": {"response_format": "url", "image": b64_uri},
        },
        timeout=120,
    )
    resp.raise_for_status()
    url = resp.json()["data"][0]["url"]
    log(f"Image uploaded: {url[:80]}...")
    return url


def submit_video(prompt, image_url=None):
    """Submit a video generation task. Returns task_id."""
    payload = {
        "model": "agnes-video-v2.0",
        "prompt": prompt,
        "width": VIDEO_WIDTH,
        "height": VIDEO_HEIGHT,
        "num_frames": NUM_FRAMES,
        "frame_rate": FRAME_RATE,
    }
    if image_url:
        payload["image"] = image_url
        payload["mode"] = "ti2vid"

    log(f"Submitting video task...")
    resp = requests.post(f"{BASE_URL}/videos", headers=HEADERS, json=payload, timeout=300)
    resp.raise_for_status()
    result = resp.json()
    task_id = result.get("task_id") or result.get("id")
    log(f"Task submitted: {task_id[:30]}...")
    return task_id


def poll_video(task_id, max_wait=600):
    """Poll video task until completed. Returns video URL."""
    deadline = time.time() + max_wait
    last_status = ""
    while time.time() < deadline:
        try:
            resp = requests.get(f"{BASE_URL}/videos/{task_id}", headers=HEADERS, timeout=15)
            resp.raise_for_status()
            result = resp.json()
            status = result.get("status", "")
            progress = result.get("progress", 0)

            if status != last_status:
                log(f"  Task {task_id[:20]}... status={status} progress={progress}%")
                last_status = status

            if status in ("completed", "COMPLETED"):
                video_url = (
                    result.get("video_url")
                    or result.get("url")
                    or result.get("remixed_from_video_id")
                )
                if not video_url:
                    data = result.get("data", {})
                    if isinstance(data, dict):
                        video_url = data.get("video_url") or data.get("url")
                log(f"  Video completed! URL: {video_url[:100]}...")
                return video_url

            if status in ("failed", "FAILED"):
                err = result.get("error") or "unknown error"
                log(f"  Video FAILED: {err}")
                raise RuntimeError(f"Video failed: {err}")
        except requests.exceptions.RequestException as e:
            log(f"  Poll error: {e}")

        time.sleep(15)

    raise TimeoutError(f"Video task {task_id} timed out after {max_wait}s")


def download_video(url, output_path):
    """Download video from URL to local file."""
    log(f"Downloading video to {output_path}...")
    resp = requests.get(url, timeout=300, stream=True)
    resp.raise_for_status()
    with open(output_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    log(f"  Downloaded: {output_path}")


def extract_last_frame(video_path, output_path):
    """Extract last frame from video using ffmpeg."""
    log(f"Extracting last frame from {video_path}...")
    cmd = [
        "ffmpeg", "-y",
        "-sseof", "-1",
        "-i", video_path,
        "-frames:v", "1",
        "-update", "1",
        output_path,
    ]
    subprocess.run(cmd, capture_output=True, timeout=30, check=True)
    log(f"  Last frame: {output_path}")


def generate_transition_frame(image_url, next_scene_prompt, output_path):
    """Generate transition frame via img2img."""
    log(f"Generating transition frame via img2img...")
    transition_prompt = (
        f"Cinematic transition frame, blending the end of the current scene "
        f"into the beginning of the next. Keep the same person and face exactly. "
        f"Next scene: {next_scene_prompt[:200]}"
    )
    resp = requests.post(
        f"{BASE_URL}/images/generations",
        headers=HEADERS,
        json={
            "model": "agnes-image-2.0-flash",
            "prompt": transition_prompt,
            "size": "768x1152",
            "n": 1,
            "extra_body": {"response_format": "url", "image": image_url},
        },
        timeout=120,
    )
    resp.raise_for_status()
    result = resp.json()
    img_url = result["data"][0].get("url", "")
    log(f"  Transition frame URL: {img_url[:80]}...")

    # Download the image
    if img_url:
        resp2 = requests.get(img_url, timeout=60)
        resp2.raise_for_status()
        with open(output_path, "wb") as f:
            f.write(resp2.content)
    log(f"  Transition frame saved: {output_path}")
    return output_path


def concatenate_videos(video_paths, output_path):
    """Concatenate multiple videos using moviepy."""
    log(f"Concatenating {len(video_paths)} videos...")
    from moviepy import VideoFileClip, concatenate_videoclips
    clips = [VideoFileClip(p) for p in video_paths]
    final = concatenate_videoclips(clips, method="compose")
    final.write_videofile(output_path, logger="bar")
    for c in clips:
        c.close()
    log(f"Final video: {output_path}")


def main():
    os.makedirs(WORK_DIR, exist_ok=True)
    state = load_state()
    scenes = state.get("scenes", [])

    with open(os.path.join(WORK_DIR, "script.json")) as f:
        scenes = json.load(f)

    ref_img = "/home/z/my-project/upload/weixin-image.jpg"
    video_paths = []

    # Determine starting point
    completed_scenes = state.get("completed_scenes", [])

    for scene_idx in range(len(scenes)):
        scene_dir = os.path.join(WORK_DIR, f"scene_{scene_idx}")
        os.makedirs(scene_dir, exist_ok=True)
        video_path = os.path.join(scene_dir, "video.mp4")

        # Skip if already completed
        if os.path.exists(video_path) and os.path.getsize(video_path) > 1000:
            log(f"Scene {scene_idx} already exists, skipping.")
            video_paths.append(video_path)
            # Load current_image for chaining
            transition_path = os.path.join(scene_dir, "transition_to_next.png")
            if os.path.exists(transition_path):
                state["current_image"] = transition_path
                save_state(state)
            continue

        log(f"\n{'='*50}")
        log(f"SCENE {scene_idx}: {scenes[scene_idx][:80]}...")
        log(f"{'='*50}")

        # Determine image for this scene
        if scene_idx == 0:
            current_image = ref_img
        else:
            current_image = state.get("current_image", ref_img)

        # Upload current image to get URL
        if os.path.exists(current_image) and not current_image.startswith("http"):
            current_image_url = upload_image_to_url(current_image)
        else:
            current_image_url = current_image
            log(f"Using existing URL: {current_image_url[:80]}...")

        # Submit video
        task_id = submit_video(scenes[scene_idx], current_image_url)
        state[f"scene{scene_idx}_task_id"] = task_id
        save_state(state)

        # Poll for completion
        video_url = poll_video(task_id, max_wait=600)

        # Download video
        download_video(video_url, video_path)
        video_paths.append(video_path)
        state[f"scene{scene_idx}_url"] = video_url
        save_state(state)

        # If there's a next scene, do scene chaining
        if scene_idx + 1 < len(scenes):
            last_frame_path = os.path.join(scene_dir, "last_frame.jpg")
            extract_last_frame(video_path, last_frame_path)

            # Upload last frame
            last_frame_url = upload_image_to_url(last_frame_path)

            # Generate transition frame
            transition_path = os.path.join(scene_dir, f"transition_to_{scene_idx+1}.png")
            generate_transition_frame(last_frame_url, scenes[scene_idx + 1], transition_path)
            state["current_image"] = transition_path
            save_state(state)

        # Mark completed
        if "completed_scenes" not in state:
            state["completed_scenes"] = []
        state["completed_scenes"].append(scene_idx)
        save_state(state)

    # Concatenate all videos
    final_path = os.path.join(WORK_DIR, "final_video.mp4")
    if not os.path.exists(final_path):
        concatenate_videos(video_paths, final_path)
    else:
        log("Final video already exists.")

    # Copy to download folder
    download_dir = "/home/z/my-project/download"
    os.makedirs(download_dir, exist_ok=True)
    final_copy = os.path.join(download_dir, "singing_dancing_final.mp4")
    shutil.copy2(final_path, final_copy)

    log(f"\n{'='*50}")
    log(f"ALL DONE! Final video: {final_copy}")
    log(f"{'='*50}")


if __name__ == "__main__":
    main()
