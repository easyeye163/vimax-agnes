#!/usr/bin/env python3
"""Mars Football — 5-scene t2v + ti2vid chained pipeline.
No reference image. Scene 0 = t2v, then extract last frame → img2img transition → next scene ti2vid.
"""
import json, requests, time, os, base64, mimetypes, shutil

API_KEY = "sk-IpvltJlHQGKTxzwGn0Eg0tfrscrBVMKrdjdmWc5bofC2DUP0"
BASE_URL = "https://apihub.agnes-ai.com/v1"
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
WD = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".working_dir/mars_football")
SF = os.path.join(WD, "state.json")
LF = os.path.join(WD, "pipeline.log")
DL_DIR = "/home/z/my-project/download"
FINAL_OUT = os.path.join(DL_DIR, "mars_football.mp4")
W, H, NF, FR = 1152, 768, 241, 24


def log(m):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {m}"
    print(line, flush=True)
    with open(LF, "a") as f:
        f.write(line + "\n")


def load():
    if os.path.exists(SF):
        with open(SF) as f:
            return json.load(f)
    return {}


def save(s):
    with open(SF, "w") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)


def retry_req(method, url, payload=None, max_retries=8, base_delay=60, label=""):
    for i in range(max_retries):
        try:
            if method == "GET":
                r = requests.get(url, headers=HEADERS, timeout=15)
            else:
                r = requests.post(url, headers=HEADERS, json=payload, timeout=120)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 502, 503, 504):
                delay = base_delay * (i + 1)
                log(f"  {label} HTTP {r.status_code}, wait {delay}s...")
                time.sleep(delay)
                continue
            raise RuntimeError(f"{label} HTTP {r.status_code}: {r.text[:200]}")
        except requests.exceptions.Timeout:
            delay = base_delay * (i + 1)
            log(f"  {label} timeout, wait {delay}s...")
            time.sleep(delay)
        except RuntimeError:
            raise
        except Exception as e:
            delay = base_delay * (i + 1)
            log(f"  {label} error: {e}, wait {delay}s...")
            time.sleep(delay)
    raise RuntimeError(f"{label}: failed after {max_retries} retries")


def upload_img(path):
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    mime = mimetypes.guess_type(path)[0] or "image/png"
    uri = f"data:{mime};base64,{b64}"
    result = retry_req("POST", f"{BASE_URL}/images/generations", {
        "model": "agnes-image-2.1-flash", "prompt": "exact same image, keep everything unchanged",
        "n": 1, "size": "1024x1024",
        "extra_body": {"response_format": "url", "image": uri}
    }, label=f"upload({os.path.basename(path)})")
    url = result["data"][0]["url"]
    log(f"  Uploaded: {url[:60]}...")
    return url


def gen_img(prompt, size, ref_img=None):
    """Generate image, optionally with reference (img2img)."""
    payload = {
        "model": "agnes-image-2.1-flash", "prompt": prompt,
        "n": 1, "size": size
    }
    if ref_img:
        if ref_img.startswith(("http://", "https://")):
            payload["extra_body"] = {"image": ref_img}
        else:
            with open(ref_img, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            mime = mimetypes.guess_type(ref_img)[0] or "image/png"
            payload["extra_body"] = {"image": f"data:{mime};base64,{b64}"}
    result = retry_req("POST", f"{BASE_URL}/images/generations", payload, label="gen_img")
    return result["data"][0].get("url", "")


def download(url, path):
    r = requests.get(url, timeout=300, stream=True)
    with open(path, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)
    log(f"  DL: {os.path.basename(path)} ({os.path.getsize(path)//1024}KB)")


def submit_t2v(prompt):
    """Submit text-to-video (no image)."""
    payload = {
        "model": "agnes-video-v2.0", "prompt": prompt,
        "width": W, "height": H, "num_frames": NF, "frame_rate": FR,
    }
    result = retry_req("POST", f"{BASE_URL}/videos", payload, label="submit_t2v")
    tid = result.get("task_id") or result.get("id")
    log(f"  T2V submitted: {tid[:30]}...")
    return tid


def submit_ti2vid(prompt, img_url):
    """Submit image-to-video."""
    payload = {
        "model": "agnes-video-v2.0", "prompt": prompt,
        "width": W, "height": H, "num_frames": NF, "frame_rate": FR,
        "image": img_url, "mode": "ti2vid",
    }
    result = retry_req("POST", f"{BASE_URL}/videos", payload, label="submit_ti2vid")
    tid = result.get("task_id") or result.get("id")
    log(f"  TI2VID submitted: {tid[:30]}...")
    return tid


def wait_for_video(tid, max_wait=480):
    deadline = time.time() + max_wait
    last_st = ""
    while time.time() < deadline:
        try:
            d = retry_req("GET", f"{BASE_URL}/videos/{tid}", label=f"poll({tid[:15]})")
            st = d.get("status", "")
            pr = d.get("progress", 0)
            if st != last_st:
                log(f"  [{tid[:15]}] {st} {pr}%")
                last_st = st
            if st in ("completed", "COMPLETED"):
                vurl = d.get("video_url") or d.get("url") or d.get("remixed_from_video_id")
                return vurl
            if st in ("failed", "FAILED"):
                raise RuntimeError(f"Video failed: {d.get('error', 'unknown')}")
        except RuntimeError:
            raise
        except Exception as e:
            log(f"  Poll err: {e}")
        time.sleep(20)
    raise TimeoutError(f"Video {tid[:15]} timed out")


def main():
    os.makedirs(WD, exist_ok=True)

    with open(f"{WD}/script.json") as f:
        scenes = json.load(f)
    with open(f"{WD}/transitions.json") as f:
        transitions = json.load(f)

    state = load()
    n = len(scenes)
    log(f"MARS FOOTBALL — {n} scenes, {W}x{H}")

    current_img_url = None  # no reference image for scene 0

    for si in range(n):
        sd = os.path.join(WD, f"scene_{si}")
        vp = os.path.join(sd, "video.mp4")
        os.makedirs(sd, exist_ok=True)

        if os.path.exists(vp) and os.path.getsize(vp) > 10000:
            log(f"Scene {si}: exists ({os.path.getsize(vp)//1024}KB), skip")
            # Use last frame for next scene if available
            lf_url = state.get(f"s{si}_lf_url")
            if lf_url:
                current_img_url = lf_url
            continue

        log(f"\n{'='*50}\nSCENE {si}/{n-1}\n{'='*50}")

        # Check existing task
        etid = state.get(f"s{si}_task")
        if etid:
            log(f"  Check task: {etid[:20]}...")
            try:
                d = retry_req("GET", f"{BASE_URL}/videos/{etid}", label=f"check({etid[:15]})")
                st = d.get("status", "")
                if st in ("completed", "COMPLETED"):
                    vurl = d.get("video_url") or d.get("url") or d.get("remixed_from_video_id")
                    download(vurl, vp)
                    state[f"s{si}_url"] = vurl
                    save(state)
                    log(f"  Scene {si}: downloaded ({os.path.getsize(vp)//1024}KB)")
                    # Get last frame for next scene
                    current_img_url = state.get(f"s{si}_lf_url")
                    continue
                elif st in ("failed", "FAILED"):
                    log(f"  Task failed, resubmit")
                else:
                    vurl = wait_for_video(etid)
                    download(vurl, vp)
                    state[f"s{si}_url"] = vurl
                    save(state)
                    log(f"  Scene {si}: completed ({os.path.getsize(vp)//1024}KB)")
                    current_img_url = state.get(f"s{si}_lf_url")
                    continue
            except (TimeoutError, RuntimeError) as e:
                log(f"  Task error: {e}, resubmit")

        # Submit video
        if current_img_url and si > 0:
            tid = submit_ti2vid(scenes[si], current_img_url)
        else:
            tid = submit_t2v(scenes[si])
        state[f"s{si}_task"] = tid
        save(state)

        # Wait for video
        vurl = wait_for_video(tid)
        download(vurl, vp)
        state[f"s{si}_url"] = vurl
        save(state)
        log(f"  Scene {si}: completed ({os.path.getsize(vp)//1024}KB)")

        # Extract last frame for next scene's transition
        if si + 1 < n:
            log(f"  Extracting last frame for transition...")
            import subprocess
            lf_path = os.path.join(sd, "last_frame.jpg")
            subprocess.run(["ffmpeg", "-y", "-sseof", "-1", "-i", vp,
                          "-frames:v", "1", "-update", "1", lf_path],
                         capture_output=True, timeout=30, check=True)

            # Generate transition frame via img2img
            if si < len(transitions):
                log(f"  Generating transition frame...")
                trans_prompt = transitions[si]
                lf_url = upload_img(lf_path)
                trans_url = gen_img(trans_prompt, f"{W}x{H}", ref_img=lf_url)
                if trans_url:
                    # Download and upload transition as next scene's first frame
                    trans_path = os.path.join(sd, f"transition_{si+1}.png")
                    download(trans_url, trans_path)
                    current_img_url = upload_img(trans_path)
                    state[f"s{si}_lf_url"] = current_img_url
                    save(state)
                    log(f"  Transition frame ready for scene {si+1}")
                else:
                    current_img_url = lf_url
                    state[f"s{si}_lf_url"] = lf_url
                    save(state)
            else:
                lf_url = upload_img(lf_path)
                current_img_url = lf_url
                state[f"s{si}_lf_url"] = lf_url
                save(state)

    # Concat
    log("\n" + "=" * 50)
    log("CONCATENATING")
    log("=" * 50)
    vps = [os.path.join(WD, f"scene_{i}", "video.mp4") for i in range(n)
           if os.path.exists(os.path.join(WD, f"scene_{i}", "video.mp4"))
           and os.path.getsize(os.path.join(WD, f"scene_{i}", "video.mp4")) > 10000]

    fv = os.path.join(WD, "final_video.mp4")
    if vps and (not os.path.exists(fv) or os.path.getsize(fv) < 10000):
        log(f"Concatenating {len(vps)} videos...")
        from moviepy import VideoFileClip, concatenate_videoclips
        clips = [VideoFileClip(p) for p in vps]
        fc = concatenate_videoclips(clips, method="compose")
        fc.write_videofile(fv, logger="bar")
        for c in clips:
            c.close()

    os.makedirs(DL_DIR, exist_ok=True)
    shutil.copy2(fv, FINAL_OUT)
    log(f"\n🎉 DONE! Final: {FINAL_OUT} ({os.path.getsize(FINAL_OUT)//1024}KB)")
    state["final"] = FINAL_OUT
    state["done"] = True
    save(state)


if __name__ == "__main__":
    while True:
        try:
            main()
            break
        except Exception as e:
            log(f"PIPELINE ERROR: {e}")
            import traceback
            log(traceback.format_exc())
            log("Retrying in 120s...")
            time.sleep(120)
