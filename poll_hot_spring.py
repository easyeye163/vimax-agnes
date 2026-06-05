#!/usr/bin/env python3
"""Poll hot spring selfie scenes, concat when all done.
Run via cron every 5 minutes.
"""
import json, requests, os, shutil, time

API_KEY = "sk-IpvltJlHQGKTxzwGn0Eg0tfrscrBVMKrdjdmWc5bofC2DUP0"
H = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
BASE = "https://apihub.agnes-ai.com/v1"
WD = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".working_dir/hot_spring_selfie")
LOG = os.path.join(WD, "poll.log")
DL_DIR = "/home/z/my-project/download"
FINAL_OUT = os.path.join(DL_DIR, "hot_spring_selfie.mp4")


def log(m):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG, "a") as f:
        f.write(f"[{ts}] {m}\n")


def main():
    os.makedirs(WD, exist_ok=True)

    # Check if script exists
    script_path = os.path.join(WD, "script.json")
    state_path = os.path.join(WD, "kf_state.json")

    if not os.path.exists(script_path) or not os.path.exists(state_path):
        log("Script or state not found — pipeline not started yet")
        return

    with open(script_path) as f:
        scenes = json.load(f)
    with open(state_path) as f:
        state = json.load(f)

    n = len(scenes)
    all_done = True

    for si in range(n):
        vp = os.path.join(WD, f"scene_{si}", "video.mp4")
        if os.path.exists(vp) and os.path.getsize(vp) > 10000:
            continue

        all_done = False
        tid = state.get(f"s{si}_task")
        if not tid:
            log(f"Scene {si}: no task submitted")
            continue

        try:
            r = requests.get(f"{BASE}/videos/{tid}", headers=H, timeout=15)
            d = r.json()
            st = d.get("status", "")
            pr = d.get("progress", 0)

            if st in ("completed", "COMPLETED"):
                vurl = d.get("video_url") or d.get("url") or d.get("remixed_from_video_id")
                if vurl:
                    os.makedirs(os.path.dirname(vp), exist_ok=True)
                    r2 = requests.get(vurl, timeout=300, stream=True)
                    with open(vp, "wb") as f:
                        for c in r2.iter_content(8192):
                            f.write(c)
                    sz = os.path.getsize(vp)
                    state[f"s{si}_url"] = vurl
                    log(f"Scene {si}: downloaded ({sz//1024}KB) from {tid[:20]}")
                else:
                    log(f"Scene {si}: completed but no URL! {json.dumps(d)[:200]}")

            elif st in ("failed", "FAILED"):
                err = d.get("error", "unknown")
                log(f"Scene {si}: FAILED - {err}")
            else:
                log(f"Scene {si}: {st} {pr}%")
        except Exception as e:
            log(f"Scene {si}: poll error - {e}")

    # Save state
    with open(state_path, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    # Count done
    done = sum(1 for i in range(n) if os.path.exists(f"{WD}/scene_{i}/video.mp4")
              and os.path.getsize(f"{WD}/scene_{i}/video.mp4") > 10000)

    # Concat if all done
    if done == n:
        fv = os.path.join(WD, "final_video.mp4")
        if not os.path.exists(fv) or os.path.getsize(fv) < 10000:
            log(f"All {n} scenes done! Concatenating...")
            from moviepy import VideoFileClip, concatenate_videoclips
            clips = [VideoFileClip(f"{WD}/scene_{i}/video.mp4") for i in range(n)]
            fc = concatenate_videoclips(clips, method="compose")
            fc.write_videofile(fv, logger="bar")
            for c in clips:
                c.close()
            log(f"Concatenated: {fv}")

        os.makedirs(DL_DIR, exist_ok=True)
        shutil.copy2(fv, FINAL_OUT)
        log(f"Final video: {FINAL_OUT}")
        state["done"] = True
        state["final"] = FINAL_OUT
        with open(state_path, "w") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    else:
        log(f"Progress: {done}/{n} scenes done")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"ERROR: {e}")
        import traceback
        log(traceback.format_exc())
