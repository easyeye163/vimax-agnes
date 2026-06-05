#!/usr/bin/env python3
"""Complete keyframes pipeline: end-frame-as-first-frame approach.
Uses ti2vid mode with each scene's end frame as the next scene's first frame.
Runs in background, handles queuing, all 3 scenes + concatenation.
"""
import json, requests, time, os, base64, mimetypes, shutil, subprocess

API_KEY = "sk-IpvltJlHQGKTxzwGn0Eg0tfrscrBVMKrdjdmWc5bofC2DUP0"
BASE_URL = "https://apihub.agnes-ai.com/v1"
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
WD = ".working_dir/idea2video"
SF = os.path.join(WD, "kf_state.json")
LF = os.path.join(WD, "kf_log.txt")
W, H, NF, FR = 768, 1152, 241, 24

def log(m):
    print(m, flush=True)
    with open(LF, "a") as f: f.write(f"[{time.strftime('%H:%M:%S')}] {m}\n")

def load(): 
    return json.load(open(SF)) if os.path.exists(SF) else {}

def save(s):
    json.dump(s, open(SF,"w"), ensure_ascii=False, indent=2)

def upload(p):
    if p.startswith("http"):
        d = p
    else:
        with open(p,"rb") as f: b = base64.b64encode(f.read()).decode()
        d = f'data:{mimetypes.guess_type(p)[0] or "image/png"};base64,{b}'
    r = requests.post(f"{BASE_URL}/images/generations", headers=HEADERS, json={
        "model":"agnes-image-2.1-flash","prompt":"exact same image","n":1,"size":"1024x1024",
        "extra_body":{"response_format":"url","image":d}}, timeout=180)
    r.raise_for_status()
    u = r.json()["data"][0]["url"]
    log(f"  uploaded: {u[:50]}")
    return u

def t2i(prompt, size):
    r = requests.post(f"{BASE_URL}/images/generations", headers=HEADERS, json={
        "model":"agnes-image-2.1-flash","prompt":prompt,"n":1,"size":size}, timeout=120)
    r.raise_for_status()
    return r.json()["data"][0].get("url","")

def dl(url, path):
    r = requests.get(url, timeout=300, stream=True)
    with open(path,"wb") as f:
        for chunk in r.iter_content(8192): f.write(chunk)
    log(f"  dl: {path} ({os.path.getsize(path)//1024}KB)")

def submit(prompt, img_url):
    r = requests.post(f"{BASE_URL}/videos", headers=HEADERS, json={
        "model":"agnes-video-v2.0","prompt":prompt,
        "width":W,"height":H,"num_frames":NF,"frame_rate":FR,
        "image":img_url,"mode":"ti2vid"}, timeout=300)
    r.raise_for_status()
    t = r.json().get("task_id") or r.json().get("id")
    log(f"  task: {t[:30]}")
    return t

def poll(tid, mx=600):
    dl2 = time.time() + mx
    while time.time() < dl2:
        try:
            r = requests.get(f"{BASE_URL}/videos/{tid}", headers=HEADERS, timeout=15)
            d = r.json()
            st = d.get("status","")
            if st in ("completed","COMPLETED"):
                u = d.get("video_url") or d.get("url") or d.get("remixed_from_video_id")
                log(f"  done: {u[:60]}")
                return u
            if st in ("failed","FAILED"):
                raise RuntimeError(d.get("error","fail"))
            log(f"  ... {st} {d.get('progress',0)}%")
        except RuntimeError: raise
        except Exception as e: log(f"  err: {e}")
        time.sleep(20)
    raise TimeoutError("timeout")

def main():
    os.makedirs(WD, exist_ok=True)
    s = load()
    scenes = json.load(open(os.path.join(WD,"script.json")))
    eframes = json.load(open(os.path.join(WD,"end_frame_prompts.json")))
    
    # Scene 0: use reference image as first frame
    if not s.get("ref_url"):
        log("Uploading ref image...")
        s["ref_url"] = upload("/home/z/my-project/upload/weixin-image.jpg")
        save(s)
    current_url = s["ref_url"]
    
    for si in range(len(scenes)):
        sd = os.path.join(WD, f"scene_{si}")
        vp = os.path.join(sd, "video.mp4")
        os.makedirs(sd, exist_ok=True)
        
        if os.path.exists(vp) and os.path.getsize(vp) > 10000:
            log(f"Scene {si} exists, skip")
            current_url = s.get(f"s{si}_ef_url", current_url)
            continue
        
        log(f"\n{'='*50}\nSCENE {si}\n{'='*50}")
        
        # Generate end frame image for this scene
        efp = os.path.join(sd, "end_frame.png")
        if not os.path.exists(efp) or os.path.getsize(efp) < 1000:
            log(f"  gen end frame {si}...")
            eu = t2i(eframes[si], f"{W}x{H}")
            dl(eu, efp)
        
        # Upload current first frame
        log(f"  upload first frame...")
        fu = upload(current_url)
        
        # Submit video
        log(f"  submit scene {si}...")
        tid = submit(scenes[si], fu)
        s[f"s{si}_task"] = tid
        save(s)
        
        # Wait + download
        vurl = poll(tid)
        dl(vurl, vp)
        s[f"s{si}_url"] = vurl
        save(s)
        
        # Upload end frame for next scene's first frame
        log(f"  upload end frame for next scene...")
        efu = upload(efp)
        s[f"s{si}_ef_url"] = efu
        save(s)
        current_url = efu
    
    # Concatenate
    vps = [os.path.join(WD,f"scene_{i}","video.mp4") for i in range(len(scenes)) 
           if os.path.exists(os.path.join(WD,f"scene_{i}","video.mp4")) and os.path.getsize(os.path.join(WD,f"scene_{i}","video.mp4")) > 10000]
    fv = os.path.join(WD, "final_video_kf.mp4")
    if vps and (not os.path.exists(fv) or os.path.getsize(fv) < 10000):
        log(f"Concatenating {len(vps)} videos...")
        from moviepy import VideoFileClip, concatenate_videoclips
        clips = [VideoFileClip(p) for p in vps]
        fc = concatenate_videoclips(clips, method="compose")
        fc.write_videofile(fv, logger="bar")
        for c in clips: c.close()
    
    out = "/home/z/my-project/download/singing_dancing_keyframes.mp4"
    shutil.copy2(fv, out)
    log(f"\n🎉 DONE: {out}")
    s["final"] = out
    save(s)

if __name__ == "__main__":
    try: main()
    except Exception as e:
        log(f"ERROR: {e}")
        import traceback; log(traceback.format_exc())
