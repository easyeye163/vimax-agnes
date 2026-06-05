#!/usr/bin/env python3
"""Persistent keyframes pipeline with aggressive retry.

Runs in a loop, continuously retrying failed/queued tasks until all scenes
are complete. Handles API overload gracefully with exponential backoff.
"""
import json, requests, time, os, base64, mimetypes, shutil

API_KEY = "sk-IpvltJlHQGKTxzwGn0Eg0tfrscrBVMKrdjdmWc5bofC2DUP0"
BASE_URL = "https://apihub.agnes-ai.com/v1"
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
WD = ".working_dir/idea2video"
SF = os.path.join(WD, "kf_state.json")
LF = os.path.join(WD, "kf_persistent.log")
W, H, NF, FR = 768, 1152, 241, 24


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


def retry_request(method, url, payload=None, max_retries=8, base_delay=60, label=""):
    """HTTP request with aggressive retry for 429/5xx/timeout."""
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

            # Unrecoverable error
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
    """Upload image to hosted URL."""
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    mime = mimetypes.guess_type(path)[0] or "image/png"
    uri = f"data:{mime};base64,{b64}"
    result = retry_request("POST", f"{BASE_URL}/images/generations", {
        "model": "agnes-image-2.1-flash", "prompt": "exact same image",
        "n": 1, "size": "1024x1024",
        "extra_body": {"response_format": "url", "image": uri}
    }, label=f"upload({os.path.basename(path)})")
    url = result["data"][0]["url"]
    log(f"  Uploaded: {url[:60]}...")
    return url


def gen_t2i(prompt, size):
    result = retry_request("POST", f"{BASE_URL}/images/generations", {
        "model": "agnes-image-2.1-flash", "prompt": prompt,
        "n": 1, "size": size
    }, label="t2i")
    return result["data"][0].get("url", "")


def download(url, path):
    r = requests.get(url, timeout=300, stream=True)
    with open(path, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)
    log(f"  DL: {os.path.basename(path)} ({os.path.getsize(path)//1024}KB)")


def submit_video(prompt, img_urls):
    """Submit keyframes video with retry."""
    payload = {
        "model": "agnes-video-v2.0", "prompt": prompt,
        "width": W, "height": H, "num_frames": NF, "frame_rate": FR,
        "extra_body": {"image": img_urls, "mode": "keyframes"}
    }
    result = retry_request("POST", f"{BASE_URL}/videos", payload,
                          label="submit_keyframes")
    tid = result.get("task_id") or result.get("id")
    log(f"  Submitted: {tid[:30]}...")
    return tid


def wait_for_video(tid, max_wait=480):
    """Wait for video to complete, return URL."""
    deadline = time.time() + max_wait
    last_st = ""
    while time.time() < deadline:
        try:
            d = retry_request("GET", f"{BASE_URL}/videos/{tid}",
                            label=f"poll({tid[:15]})")
            st = d.get("status", "")
            pr = d.get("progress", 0)
            if st != last_st:
                log(f"  [{tid[:15]}] {st} {pr}%")
                last_st = st

            if st in ("completed", "COMPLETED"):
                vurl = d.get("video_url") or d.get("url") or d.get("remixed_from_video_id")
                return vurl
            if st in ("failed", "FAILED"):
                raise RuntimeError(f"Video failed: {d.get('error','unknown')}")
        except RuntimeError:
            raise
        except Exception as e:
            log(f"  Poll err: {e}")
        time.sleep(20)
    raise TimeoutError(f"Video {tid[:15]} timed out")


def main():
    os.makedirs(WD, exist_ok=True)
    state = load()

    with open(os.path.join(WD, "script.json")) as f:
        scenes = json.load(f)
    with open(os.path.join(WD, "end_frame_prompts.json")) as f:
        end_frames = json.load(f)

    ref_img = "/home/z/my-project/upload/weixin-image.jpg"

    # Upload ref once
    if not state.get("ref_uploaded_url"):
        log("Uploading reference image...")
        state["ref_uploaded_url"] = upload_img(ref_img)
        save(state)

    current_ff = state.get("ref_uploaded_url")

    for si in range(len(scenes)):
        sd = os.path.join(WD, f"scene_{si}")
        vp = os.path.join(sd, "video.mp4")
        os.makedirs(sd, exist_ok=True)

        if os.path.exists(vp) and os.path.getsize(vp) > 10000:
            log(f"Scene {si}: exists, skip")
            current_ff = state.get(f"s{si}_ef_url", current_ff)
            continue

        log(f"\n{'='*50}\nSCENE {si} (keyframes)\n{'='*50}")

        # Gen end frame
        efp = os.path.join(sd, "end_frame.png")
        if not os.path.exists(efp) or os.path.getsize(efp) < 1000:
            log(f"  Gen end frame...")
            eu = gen_t2i(end_frames[si], f"{W}x{H}")
            download(eu, efp)

        # Upload end frame
        if not state.get(f"s{si}_ef_url"):
            log(f"  Upload end frame...")
            state[f"s{si}_ef_url"] = upload_img(efp)
            save(state)
        ef_url = state[f"s{si}_ef_url"]

        # Try existing task
        etid = state.get(f"s{si}_task")
        if etid:
            log(f"  Check task: {etid[:20]}...")
            try:
                d = retry_request("GET", f"{BASE_URL}/videos/{etid}",
                                label=f"check({etid[:15]})")
                st = d.get("status", "")
                if st in ("completed", "COMPLETED"):
                    vurl = d.get("video_url") or d.get("url") or d.get("remixed_from_video_id")
                    download(vurl, vp)
                    state[f"s{si}_url"] = vurl
                    save(state)
                    current_ff = ef_url
                    continue
                elif st in ("failed", "FAILED"):
                    log(f"  Task failed, resubmit")
                else:
                    # Wait for it
                    vurl = wait_for_video(etid)
                    download(vurl, vp)
                    state[f"s{si}_url"] = vurl
                    save(state)
                    current_ff = ef_url
                    continue
            except (TimeoutError, RuntimeError) as e:
                log(f"  Task error: {e}, resubmit")

        # Submit new task
        log(f"  FF: {current_ff[:50]}...")
        log(f"  EF: {ef_url[:50]}...")
        tid = submit_video(scenes[si], [current_ff, ef_url])
        state[f"s{si}_task"] = tid
        save(state)

        # Wait
        vurl = wait_for_video(tid)
        download(vurl, vp)
        state[f"s{si}_url"] = vurl
        save(state)
        current_ff = ef_url

    # Concat
    vps = [os.path.join(WD, f"scene_{i}", "video.mp4") for i in range(len(scenes))
           if os.path.exists(os.path.join(WD, f"scene_{i}", "video.mp4"))
           and os.path.getsize(os.path.join(WD, f"scene_{i}", "video.mp4")) > 10000]

    fv = os.path.join(WD, "final_video_kf.mp4")
    if vps and (not os.path.exists(fv) or os.path.getsize(fv) < 10000):
        log(f"Concatenating {len(vps)} videos...")
        from moviepy import VideoFileClip, concatenate_videoclips
        clips = [VideoFileClip(p) for p in vps]
        fc = concatenate_videoclips(clips, method="compose")
        fc.write_videofile(fv, logger="bar")
        for c in clips:
            c.close()

    out = "/home/z/my-project/download/singing_dancing_keyframes.mp4"
    shutil.copy2(fv, out)
    log(f"\n🎉 DONE! Final: {out}")
    state["final"] = out
    state["done"] = True
    save(state)


if __name__ == "__main__":
    while True:
        try:
            main()
            break  # Success
        except Exception as e:
            log(f"PIPELINE ERROR: {e}")
            log("Retrying in 120s...")
            time.sleep(120)
