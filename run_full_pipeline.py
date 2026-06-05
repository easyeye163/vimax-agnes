#!/usr/bin/env python3
"""Full vimax pipeline: singing/dancing video with scene chaining.
Runs as a background daemon, checks on already-submitted tasks first.
"""
import json, os, requests, time, subprocess, base64, mimetypes, shutil

API_KEY = "sk-IpvltJlHQGKTxzwGn0Eg0tfrscrBVMKrdjdmWc5bofC2DUP0"
BASE_URL = "https://apihub.agnes-ai.com/v1"
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
WORK_DIR = ".working_dir/idea2video"
STATE_FILE = os.path.join(WORK_DIR, "task_state.json")
LOG_FILE = os.path.join(WORK_DIR, "pipeline_log.txt")
W, H, NF, FR = 768, 1152, 241, 24

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

def img_to_url(path):
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    mime = mimetypes.guess_type(path)[0] or "image/png"
    uri = f"data:{mime};base64,{b64}"
    resp = requests.post(f"{BASE_URL}/images/generations", headers=HEADERS, json={
        "model": "agnes-image-2.1-flash", "prompt": "Keep the image exactly as it is",
        "n": 1, "size": "1024x1024",
        "extra_body": {"response_format": "url", "image": uri}
    }, timeout=120)
    resp.raise_for_status()
    url = resp.json()["data"][0]["url"]
    log(f"  Uploaded: {url[:80]}...")
    return url

def submit_video(prompt, img_url=None):
    payload = {"model": "agnes-video-v2.0", "prompt": prompt,
               "width": W, "height": H, "num_frames": NF, "frame_rate": FR}
    if img_url:
        payload["image"] = img_url
        payload["mode"] = "ti2vid"
    log(f"  Submitting video...")
    resp = requests.post(f"{BASE_URL}/videos", headers=HEADERS, json=payload, timeout=300)
    resp.raise_for_status()
    tid = resp.json().get("task_id") or resp.json().get("id")
    log(f"  Task: {tid[:30]}...")
    return tid

def poll_task(tid, max_wait=480):
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            resp = requests.get(f"{BASE_URL}/videos/{tid}", headers=HEADERS, timeout=15)
            r = resp.json()
            st = r.get("status", "")
            pr = r.get("progress", 0)
            if st in ("completed", "COMPLETED"):
                url = r.get("video_url") or r.get("url") or r.get("remixed_from_video_id")
                if not url:
                    d = r.get("data", {})
                    if isinstance(d, dict):
                        url = d.get("video_url") or d.get("url")
                log(f"  Completed! URL: {url[:100]}...")
                return url
            if st in ("failed", "FAILED"):
                log(f"  FAILED: {r.get('error', 'unknown')}")
                raise RuntimeError(f"Video failed: {r.get('error')}")
            # Log every 30s
            log(f"  ... {st} {pr}%")
        except Exception as e:
            log(f"  Poll err: {e}")
        time.sleep(15)
    raise TimeoutError(f"Timed out after {max_wait}s")

def download(url, path):
    log(f"  Downloading to {path}...")
    r = requests.get(url, timeout=300, stream=True)
    r.raise_for_status()
    with open(path, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)
    sz = os.path.getsize(path)
    log(f"  Saved: {path} ({sz//1024}KB)")

def extract_last_frame(vid, out):
    subprocess.run(["ffmpeg", "-y", "-sseof", "-1", "-i", vid, "-frames:v", "1", "-update", "1", out],
                   capture_output=True, timeout=30, check=True)
    log(f"  Last frame: {out}")

def gen_transition(img_url, next_prompt, out):
    prompt = (f"Cinematic transition frame blending end of current scene into beginning of next. "
               f"Keep same person and face exactly. Next scene: {next_prompt[:200]}")
    log(f"  Generating transition via img2img...")
    resp = requests.post(f"{BASE_URL}/images/generations", headers=HEADERS, json={
        "model": "agnes-image-2.0-flash", "prompt": prompt,
        "size": "768x1152", "n": 1,
        "extra_body": {"response_format": "url", "image": img_url}
    }, timeout=120)
    resp.raise_for_status()
    url = resp.json()["data"][0].get("url", "")
    if url:
        r2 = requests.get(url, timeout=60)
        r2.raise_for_status()
        with open(out, "wb") as f:
            f.write(r2.content)
    log(f"  Transition: {out}")

def main():
    os.makedirs(WORK_DIR, exist_ok=True)
    state = load_state()
    
    with open(os.path.join(WORK_DIR, "script.json")) as f:
        scenes = json.load(f)
    
    ref_img = "/home/z/my-project/upload/weixin-image.jpg"
    video_paths = []
    
    for scene_idx in range(len(scenes)):
        scene_dir = os.path.join(WORK_DIR, f"scene_{scene_idx}")
        os.makedirs(scene_dir, exist_ok=True)
        video_path = os.path.join(scene_dir, "video.mp4")
        
        if os.path.exists(video_path) and os.path.getsize(video_path) > 10000:
            log(f"Scene {scene_idx} exists, skip.")
            video_paths.append(video_path)
            tp = os.path.join(scene_dir, "transition_to_next.png")
            if os.path.exists(tp):
                state["current_image"] = tp
                save_state(state)
            continue
        
        log(f"\n{'='*50}")
        log(f"SCENE {scene_idx}")
        log(f"{'='*50}")
        
        # Check if we already have a task_id for this scene
        existing_tid = state.get(f"scene{scene_idx}_task_id")
        
        if scene_idx == 0:
            current_img = ref_img
        else:
            current_img = state.get("current_image", ref_img)
        
        # Upload image if needed
        if os.path.exists(current_img) and not current_img.startswith("http"):
            img_url = img_to_url(current_img)
        else:
            img_url = current_img
            log(f"  Using URL: {img_url[:80]}...")
        
        if existing_tid:
            # Check if existing task is still valid
            log(f"  Checking existing task: {existing_tid[:30]}...")
            try:
                resp = requests.get(f"{BASE_URL}/videos/{existing_tid}", headers=HEADERS, timeout=15)
                r = resp.json()
                st = r.get("status", "")
                if st in ("completed", "COMPLETED"):
                    vurl = r.get("video_url") or r.get("url") or r.get("remixed_from_video_id")
                    if vurl:
                        download(vurl, video_path)
                        video_paths.append(video_path)
                        state[f"scene{scene_idx}_url"] = vurl
                        save_state(state)
                        log(f"  Downloaded from existing task!")
                        # Skip to chaining
                    else:
                        existing_tid = None  # Re-submit
                elif st in ("failed", "FAILED"):
                    log(f"  Existing task failed, re-submitting...")
                    existing_tid = None
                else:
                    log(f"  Existing task still {st} {r.get('progress')}%, polling...")
                    vurl = poll_task(existing_tid)
                    download(vurl, video_path)
                    video_paths.append(video_path)
                    state[f"scene{scene_idx}_url"] = vurl
                    save_state(state)
            except Exception as e:
                log(f"  Error checking task: {e}")
                existing_tid = None
        
        if not existing_tid or not os.path.exists(video_path) or os.path.getsize(video_path) < 10000:
            tid = submit_video(scenes[scene_idx], img_url)
            state[f"scene{scene_idx}_task_id"] = tid
            save_state(state)
            vurl = poll_task(tid)
            download(vurl, video_path)
            video_paths.append(video_path)
            state[f"scene{scene_idx}_url"] = vurl
            save_state(state)
        
        # Scene chaining: extract last frame and generate transition
        if scene_idx + 1 < len(scenes):
            lf = os.path.join(scene_dir, "last_frame.jpg")
            extract_last_frame(video_path, lf)
            lf_url = img_to_url(lf)
            tp = os.path.join(scene_dir, f"transition_to_{scene_idx+1}.png")
            gen_transition(lf_url, scenes[scene_idx + 1], tp)
            state["current_image"] = tp
            save_state(state)
    
    # Concatenate
    final = os.path.join(WORK_DIR, "final_video.mp4")
    if not os.path.exists(final) or os.path.getsize(final) < 10000:
        log(f"Concatenating {len(video_paths)} videos...")
        from moviepy import VideoFileClip, concatenate_videoclips
        clips = [VideoFileClip(p) for p in video_paths]
        fc = concatenate_videoclips(clips, method="compose")
        fc.write_videofile(final, logger="bar")
        for c in clips:
            c.close()
    
    # Copy to download
    dl = "/home/z/my-project/download/singing_dancing_final.mp4"
    shutil.copy2(final, dl)
    log(f"\n🎉 ALL DONE! Final: {dl}")
    
    # Save completion marker
    state["final_video"] = dl
    state["completed"] = True
    save_state(state)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"PIPELINE ERROR: {e}")
        import traceback
        log(traceback.format_exc())
