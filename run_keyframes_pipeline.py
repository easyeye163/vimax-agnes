#!/usr/bin/env python3
"""Keyframes pipeline runner: generates all scenes with keyframes chaining.
Checks on already-completed steps, handles all API calls.
"""
import json, requests, time, os, base64, mimetypes, shutil

API_KEY = "sk-IpvltJlHQGKTxzwGn0Eg0tfrscrBVMKrdjdmWc5bofC2DUP0"
BASE_URL = "https://apihub.agnes-ai.com/v1"
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
WORK_DIR = ".working_dir/idea2video"
STATE_FILE = os.path.join(WORK_DIR, "kf_state.json")
LOG_FILE = os.path.join(WORK_DIR, "kf_log.txt")
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

def upload_img(path):
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
    log(f"  Uploaded: {url[:60]}...")
    return url

def upload_url(url):
    """Upload a URL-based image to get a fresh hosted URL."""
    resp = requests.post(f"{BASE_URL}/images/generations", headers=HEADERS, json={
        "model": "agnes-image-2.1-flash", "prompt": "Keep the image exactly as it is",
        "n": 1, "size": "1024x1024",
        "extra_body": {"response_format": "url", "image": url}
    }, timeout=120)
    resp.raise_for_status()
    url2 = resp.json()["data"][0]["url"]
    log(f"  Re-hosted: {url2[:60]}...")
    return url2

def gen_t2i(prompt, size):
    resp = requests.post(f"{BASE_URL}/images/generations", headers=HEADERS, json={
        "model": "agnes-image-2.1-flash", "prompt": prompt,
        "n": 1, "size": size
    }, timeout=120)
    resp.raise_for_status()
    return resp.json()["data"][0].get("url", "")

def download(url, path):
    resp = requests.get(url, timeout=300, stream=True)
    with open(path, "wb") as f:
        for chunk in resp.iter_content(8192):
            f.write(chunk)
    sz = os.path.getsize(path)
    log(f"  Downloaded: {path} ({sz//1024}KB)")
    return sz

def submit_keyframes(prompt, img_urls, w=W, h=H):
    payload = {"model": "agnes-video-v2.0", "prompt": prompt,
               "width": w, "height": h, "num_frames": NF, "frame_rate": FR,
               "extra_body": {"image": img_urls, "mode": "keyframes"}}
    log(f"  Submitting keyframes video...")
    resp = requests.post(f"{BASE_URL}/videos", headers=HEADERS, json=payload, timeout=300)
    resp.raise_for_status()
    tid = resp.json().get("task_id") or resp.json().get("id")
    log(f"  Task: {tid[:30]}...")
    return tid

def poll(tid, max_wait=480):
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            resp = requests.get(f"{BASE_URL}/videos/{tid}", headers=HEADERS, timeout=15)
            d = resp.json()
            st = d.get("status", "")
            pr = d.get("progress", 0)
            if st in ("completed", "COMPLETED"):
                url = d.get("video_url") or d.get("url") or d.get("remixed_from_video_id")
                log(f"  Completed! URL: {url[:80]}...")
                return url
            if st in ("failed", "FAILED"):
                raise RuntimeError(f"Failed: {d.get('error','unknown')}")
            log(f"  ... {st} {pr}%")
        except Exception as e:
            log(f"  Poll err: {e}")
        time.sleep(15)
    raise TimeoutError(f"Timed out after {max_wait}s")

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
        
        # Check for existing task
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
                    log(f"  Task failed, resubmitting...")
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
                log(f"  Error: {e}")
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
    
    final = os.path.join(WORK_DIR, "final_video.mp4")
    if not os.path.exists(final) or os.path.getsize(final) < 10000:
        log(f"Concatenating {len(video_paths)} videos...")
        from moviepy import VideoFileClip, concatenate_videoclips
        clips = [VideoFileClip(p) for p in video_paths]
        fc = concatenate_videoclips(clips, method="compose")
        fc.write_videofile(final, logger="bar")
        for c in clips:
            c.close()
    
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
