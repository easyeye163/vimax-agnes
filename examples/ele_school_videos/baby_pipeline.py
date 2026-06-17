#!/usr/bin/env python3
"""Submit + poll + process for baby videos: baby_fruits, baby_animals, baby_objects"""
import json, os, sys, time, base64, subprocess, requests, asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed

API = "https://apihub.agnes-ai.com/v1"
KEY = "sk-IpvltJlHQGKTxzwGn0Eg0tfrscrBVMKrdjdmWc5bofC2DUP0"
HEADERS = {"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"}
WORK = "/home/z/my-project/vimax-agnes/.working_dir"
DOWNLOAD = "/home/z/my-project/download"
EPISODES = ["baby_fruits", "baby_animals", "baby_objects"]

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def submit_one(ep, i):
    ep_dir = os.path.join(WORK, ep)
    img_path = os.path.join(ep_dir, "scenes", f"scene_{i}", "first_frame.png")
    video_path = os.path.join(ep_dir, "scenes", f"scene_{i}", "video.mp4")
    if os.path.exists(video_path) and os.path.getsize(video_path) > 50000:
        return (ep, i, None)
    if not os.path.exists(img_path):
        return (ep, i, None)
    jpg_path = f"/tmp/{ep}_{i}.jpg"
    subprocess.run(f'ffmpeg -y -i "{img_path}" -q:v 5 "{jpg_path}"', shell=True, capture_output=True)
    with open(jpg_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    with open(os.path.join(ep_dir, "prompts.json")) as f:
        prompts = json.load(f)["prompts"]
    try:
        r = requests.post(f"{API}/videos", headers=HEADERS, json={
            "model": "agnes-video-v2.0", "prompt": prompts[i][:300], "image": b64, "size": "1280x720"
        }, timeout=180)
        if r.status_code == 200:
            return (ep, i, r.json()["id"])
        return (ep, i, None)
    except:
        return (ep, i, None)

phase = sys.argv[1] if len(sys.argv) > 1 else "all"

if phase in ("submit", "all"):
    log("=== Submitting ===")
    all_results = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {}
        for ep in EPISODES:
            for i in range(8):
                futures[pool.submit(submit_one, ep, i)] = (ep, i)
        for f in as_completed(futures):
            ep, i, tid = f.result()
            all_results[(ep, i)] = tid
            print(f"  {ep}/scene_{i}: {tid or 'SKIP'}", flush=True)
    for ep in EPISODES:
        task_ids = [all_results.get((ep, i)) for i in range(8)]
        with open(os.path.join(WORK, ep, "task_ids.json"), "w") as f:
            json.dump(task_ids, f)
        s = sum(1 for t in task_ids if t)
        print(f"  {ep}: {s}/8 submitted", flush=True)

if phase in ("poll", "all"):
    log("=== Polling ===")
    for ep in EPISODES:
        tid_file = os.path.join(WORK, ep, "task_ids.json")
        if not os.path.exists(tid_file): continue
        with open(tid_file) as f: task_ids = json.load(f)
        ok = 0
        for i, tid in enumerate(task_ids):
            if not tid: continue
            vp = os.path.join(WORK, ep, "scenes", f"scene_{i}", "video.mp4")
            if os.path.exists(vp) and os.path.getsize(vp) > 50000: ok += 1; continue
            try:
                r = requests.get(f"{API}/videos/{tid}", headers=HEADERS, timeout=30)
                data = r.json()
                if data.get("status") == "completed" and data.get("remixed_from_video_id"):
                    url = data["remixed_from_video_id"]
                    vr = requests.get(url, timeout=120)
                    with open(vp, "wb") as f: f.write(vr.content)
                    print(f"  DOWNLOADED {ep}/scene_{i} ({len(vr.content)//1024}KB)", flush=True)
                    ok += 1
                elif data.get("status") in ("queued", "in_progress"):
                    print(f"  PENDING {ep}/scene_{i}: {data.get('status')}", flush=True)
            except Exception as e: print(f"  ERR {ep}/scene_{i}: {e}", flush=True)
        print(f"  {ep}: {ok}/8 downloaded", flush=True)

if phase in ("process", "all"):
    import edge_tts
    os.makedirs(DOWNLOAD, exist_ok=True)
    log("=== Processing ===")
    for ep in EPISODES:
        ep_dir = os.path.join(WORK, ep)
        with open(os.path.join(ep_dir, "tts.json")) as f: tts = json.load(f)
        log(f"  {ep}: generating TTS...")
        zh_mp3 = os.path.join(ep_dir, "tts_full.mp3")
        asyncio.run(edge_tts.Communicate(tts["zh"], "zh-CN-XiaoxiaoNeural", rate="-15%").save(zh_mp3))
        dur = float(subprocess.check_output(f'ffprobe -v error -show_entries format=duration -of csv=p=0 "{zh_mp3}"', shell=True).strip())
        log(f"  {ep}: TTS {dur:.1f}s")
        padded = os.path.join(ep_dir, "tts_padded.mp3")
        subprocess.run(f'ffmpeg -y -i "{zh_mp3}" -af "apad=whole_dur=41" -c:a libmp3lame -q:a 4 "{padded}"', shell=True, capture_output=True)
        concat_file = os.path.join(ep_dir, "concat_list.txt")
        with open(concat_file, "w") as f:
            for i in range(8):
                vp = os.path.join(ep_dir, "scenes", f"scene_{i}", "video.mp4")
                if os.path.exists(vp) and os.path.getsize(vp) > 50000:
                    f.write(f"file '{vp}'\n")
        video_only = os.path.join(ep_dir, "concat_video.mp4")
        subprocess.run(f'ffmpeg -y -f concat -safe 0 -i "{concat_file}" -c copy "{video_only}"', shell=True, capture_output=True)
        out = os.path.join(DOWNLOAD, f"{ep}_hd_land.mp4")
        subprocess.run(f'ffmpeg -y -i "{video_only}" -i "{padded}" -c:v copy -c:a aac -b:a 128k -map 0:v -map 1:a -shortest "{out}"', shell=True, capture_output=True)
        size_mb = os.path.getsize(out) / (1024*1024)
        log(f"  OUTPUT: {size_mb:.1f}MB -> {out}")
log("DONE")
