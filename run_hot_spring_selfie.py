#!/usr/bin/env python3
"""
Hot Spring Selfie MV — 温泉自拍短视频
Same reference image, keyframes mode for smooth transitions.
Uses persistent retry with state management.
"""
import json, requests, time, os, base64, mimetypes, shutil

API_KEY = "sk-IpvltJlHQGKTxzwGn0Eg0tfrscrBVMKrdjdmWc5bofC2DUP0"
BASE_URL = "https://apihub.agnes-ai.com/v1"
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
WD = ".working_dir/hot_spring_selfie"
SF = os.path.join(WD, "kf_state.json")
LF = os.path.join(WD, "hot_spring.log")
W, H, NF, FR = 768, 1152, 241, 24
REF_IMG = "/home/z/my-project/upload/weixin-image.jpg"
DL_DIR = "/home/z/my-project/download"
FINAL_OUT = os.path.join(DL_DIR, "hot_spring_selfie.mp4")

# ═══════════════════════════════════════════════════════════════
# STORY IDEAS (hardcoded — same reference image, hot spring selfie theme)
# ═══════════════════════════════════════════════════════════════

IDEA = """
温泉自拍Vlog：一位美丽的女孩来到山间温泉，先是在更衣室整理打扮准备入浴，然后走进露天温泉池中享受温暖泉水，最后在温泉边摆出各种可爱的自拍姿势，记录下这美好的时刻
"""

USER_REQUIREMENT = """
3个场景，每个场景10秒，竖屏拍摄(768x1152)，电影质感，Vlog自拍风格
"""

STYLE = "电影质感Vlog自拍风格"


def log(m):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {m}"
    print(line, flush=True)
    os.makedirs(WD, exist_ok=True)
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


def chat(system_prompt, user_prompt):
    """Call Agnes chat API."""
    result = retry_request("POST", f"{BASE_URL}/chat/completions", {
        "model": "agnes-2.0-flash",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 4096,
    }, label="chat")
    return result["choices"][0]["message"]["content"]


def chat_json(system_prompt, user_prompt):
    """Call chat API and parse JSON."""
    content = chat(system_prompt, user_prompt).strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1]
        if content.endswith("```"):
            content = content[:-3]
    return json.loads(content)


def upload_img(path):
    """Upload image to hosted URL."""
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    mime = mimetypes.guess_type(path)[0] or "image/png"
    uri = f"data:{mime};base64,{b64}"
    result = retry_request("POST", f"{BASE_URL}/images/generations", {
        "model": "agnes-image-2.1-flash", "prompt": "exact same image, keep everything unchanged",
        "n": 1, "size": "1024x1024",
        "extra_body": {"response_format": "url", "image": uri}
    }, label=f"upload({os.path.basename(path)})")
    url = result["data"][0]["url"]
    log(f"  Uploaded: {url[:60]}...")
    return url


def gen_t2i(prompt, size):
    """Generate image and return URL."""
    result = retry_request("POST", f"{BASE_URL}/images/generations", {
        "model": "agnes-image-2.1-flash", "prompt": prompt,
        "n": 1, "size": size
    }, label="t2i")
    return result["data"][0].get("url", "")


def download(url, path):
    """Download file from URL."""
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


# ═══════════════════════════════════════════════════════════════
# STEP 1: Generate Story
# ═══════════════════════════════════════════════════════════════

def step1_story():
    story_path = os.path.join(WD, "story.txt")
    if os.path.exists(story_path):
        with open(story_path) as f:
            log(f"Story loaded from cache ({os.path.getsize(story_path)} bytes)")
            return f.read()

    log("\n" + "=" * 60)
    log("STEP 1: Developing story...")
    log("=" * 60)

    system_prompt = """\
You are a seasoned creative story generation expert. You expand ideas into \
well-structured stories with clear scenes, characters, and dialogue.

[Output] A complete story in paragraphs with:
- Story Title
- Target Audience & Genre
- Story Outline (1 paragraph)
- Main Characters Introduction (with detailed appearance descriptions)
- Full Story Narrative (Introduction -> Development -> Climax -> Conclusion)

IMPORTANT: Write the story in the SAME LANGUAGE as the input idea.
Keep it concise but vivid, suitable for adaptation into short video scenes.
Include DETAILED character appearance descriptions (clothing, body type, \
hair, distinguishing features, color palette) to enable consistent image generation.
"""
    user_prompt = f"""\
<idea>
{IDEA}
</idea>

<user_requirement>
{USER_REQUIREMENT}
</user_requirement>

<style>
{STYLE}
</style>
"""
    story = chat(system_prompt, user_prompt)
    with open(story_path, "w") as f:
        f.write(story)
    log(f"Story saved ({len(story)} chars)")
    log(f"Preview: {story[:200]}...")
    return story


# ═══════════════════════════════════════════════════════════════
# STEP 2: Write Script (visual prompts for each scene)
# ═══════════════════════════════════════════════════════════════

def step2_script(story):
    script_path = os.path.join(WD, "script.json")
    if os.path.exists(script_path):
        with open(script_path) as f:
            scenes = json.load(f)
            log(f"Script loaded from cache ({len(scenes)} scenes)")
            return scenes

    log("\n" + "=" * 60)
    log("STEP 2: Writing script (visual prompts for video generation)...")
    log("=" * 60)

    system_prompt = """\
You are a professional video director and visual prompt engineer. Adapt the \
given story into detailed visual scene descriptions for AI video generation.

[Output Format] Return a JSON object:
{
  "scenes": [
    "Scene 1 visual prompt (detailed English description for video generation)...",
    "Scene 2 visual prompt...",
    ...
  ]
}

Rules:
- Each scene MUST be a detailed VISUAL DESCRIPTION in ENGLISH, suitable for AI video generation.
- Do NOT include character names in angle brackets or dialogue tags.
- Focus on: camera movement, lighting, colors, environment, character actions, atmosphere, mood.
- Include specific visual details: lens type (wide/telephoto), depth of field, camera angle, \
lighting direction, color grading, particle effects, weather.
- Each scene should be 80-150 words, rich in cinematic detail.
- Maintain visual consistency across scenes (same character appearance, coherent world).
- Number of scenes MUST respect the user requirement constraints.
- The art style should match the requested style (realistic cinematic, anime, etc.).
- Describe MOTION and ACTION, not static images — this is for video generation.
"""
    user_prompt = f"""\
<story>
{story}
</story>

<user_requirement>
{USER_REQUIREMENT}
</user_requirement>

<style>
{STYLE}
</style>
"""
    result = chat_json(system_prompt, user_prompt)
    scenes = result.get("scenes", [])
    with open(script_path, "w") as f:
        json.dump(scenes, f, ensure_ascii=False, indent=2)
    log(f"Script saved ({len(scenes)} scenes)")
    for i, s in enumerate(scenes):
        log(f"  Scene {i}: {s[:100]}...")
    return scenes


# ═══════════════════════════════════════════════════════════════
# STEP 3: Generate end frame prompts for keyframes mode
# ═══════════════════════════════════════════════════════════════

def step3_end_frame_prompts(scenes):
    ef_path = os.path.join(WD, "end_frame_prompts.json")
    if os.path.exists(ef_path):
        with open(ef_path) as f:
            ef = json.load(f)
            log(f"End frame prompts loaded from cache ({len(ef)})")
            return ef

    log("\n" + "=" * 60)
    log("STEP 3: Generating end frame prompts for keyframes mode...")
    log("=" * 60)

    scenes_text = ""
    for i, scene in enumerate(scenes):
        scenes_text += f"\nScene {i}: {scene}\n"

    system_prompt = """\
You are a visual prompt engineer for AI image generation. For each video scene \
description below, generate a STATIC image prompt that represents what the scene \
looks like at its very END — the final frame of the video.

[Output Format] Return a JSON object:
{
  "end_frames": [
    "End frame image prompt for Scene 0 (STATIC, detailed, English)...",
    "End frame image prompt for Scene 1...",
    ...
  ]
}

Rules:
- Each prompt must describe a STATIC frozen moment, NOT motion or action verbs.
- The end frame must be visually consistent with the scene description — \
same character, same outfit, same environment, same lighting.
- Focus on: pose, facial expression, hand position, body posture, camera angle, \
lighting, background elements — everything visible in a single frozen frame.
- Include art style matching the scene (e.g., "realistic cinematic").
- The character's appearance (face, body, clothing) must remain EXACTLY the same \
across ALL end frames — only the pose, expression, and environment change.
- Each prompt should be 3-5 sentences, rich in visual detail.
- MUST be in ENGLISH for best image generation results.
"""
    user_prompt = f"""\
<style>{STYLE}</style>

{scenes_text}
"""
    result = chat_json(system_prompt, user_prompt)
    end_frames = result.get("end_frames", [])
    with open(ef_path, "w") as f:
        json.dump(end_frames, f, ensure_ascii=False, indent=2)
    log(f"End frame prompts saved ({len(end_frames)})")
    for i, p in enumerate(end_frames):
        log(f"  EF {i}: {p[:100]}...")
    return end_frames


# ═══════════════════════════════════════════════════════════════
# STEP 4: Generate videos with keyframes chaining (persistent)
# ═══════════════════════════════════════════════════════════════

def step4_videos(scenes, end_frames):
    state = load()

    # Upload ref image once
    if not state.get("ref_uploaded_url"):
        log("Uploading reference image...")
        state["ref_uploaded_url"] = upload_img(REF_IMG)
        save(state)

    current_ff = state["ref_uploaded_url"]

    for si in range(len(scenes)):
        sd = os.path.join(WD, f"scene_{si}")
        vp = os.path.join(sd, "video.mp4")
        os.makedirs(sd, exist_ok=True)

        if os.path.exists(vp) and os.path.getsize(vp) > 10000:
            log(f"Scene {si}: exists ({os.path.getsize(vp)//1024}KB), skip")
            current_ff = state.get(f"s{si}_ef_url", current_ff)
            continue

        log(f"\n{'='*50}\nSCENE {si} (keyframes)\n{'='*50}")

        # Gen end frame image
        efp = os.path.join(sd, "end_frame.png")
        if not os.path.exists(efp) or os.path.getsize(efp) < 1000:
            log(f"  Gen end frame image...")
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
            log(f"  Check existing task: {etid[:20]}...")
            try:
                d = retry_request("GET", f"{BASE_URL}/videos/{etid}",
                                label=f"check({etid[:15]})")
                st = d.get("status", "")
                if st in ("completed", "COMPLETED"):
                    vurl = d.get("video_url") or d.get("url") or d.get("remixed_from_video_id")
                    download(vurl, vp)
                    state[f"s{si}_url"] = vurl
                    save(state)
                    log(f"  Scene {si}: downloaded ({os.path.getsize(vp)//1024}KB)")
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
                    log(f"  Scene {si}: completed ({os.path.getsize(vp)//1024}KB)")
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
        log(f"  Scene {si}: completed ({os.path.getsize(vp)//1024}KB)")
        current_ff = ef_url

    return state


# ═══════════════════════════════════════════════════════════════
# STEP 5: Concatenate all videos
# ═══════════════════════════════════════════════════════════════

def step5_concat():
    vps = []
    for i in range(20):  # scan up to 20 scenes
        vp = os.path.join(WD, f"scene_{i}", "video.mp4")
        if os.path.exists(vp) and os.path.getsize(vp) > 10000:
            vps.append(vp)
        else:
            break

    if not vps:
        log("ERROR: No completed scenes found!")
        return None

    fv = os.path.join(WD, "final_video.mp4")
    if os.path.exists(fv) and os.path.getsize(fv) > 10000:
        log(f"Final video exists ({os.path.getsize(fv)//1024}KB)")
        return fv

    log(f"Concatenating {len(vps)} videos...")
    from moviepy import VideoFileClip, concatenate_videoclips
    clips = [VideoFileClip(p) for p in vps]
    fc = concatenate_videoclips(clips, method="compose")
    fc.write_videofile(fv, logger="bar")
    for c in clips:
        c.close()
    log(f"Concatenated: {fv} ({os.path.getsize(fv)//1024}KB)")
    return fv


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    os.makedirs(WD, exist_ok=True)

    log("══════════════════════════════════════════════════")
    log("HOT SPRING SELFIE MV — 温泉自拍短视频")
    log("══════════════════════════════════════════════════")

    # Steps 1-3: Story, Script, End Frame Prompts (cached after first run)
    story = step1_story()
    scenes = step2_script(story)
    end_frames = step3_end_frame_prompts(scenes)

    # Step 4: Generate videos (persistent retry)
    state = step4_videos(scenes, end_frames)

    # Step 5: Concatenate
    fv = step5_concat()
    if fv:
        os.makedirs(DL_DIR, exist_ok=True)
        shutil.copy2(fv, FINAL_OUT)
        log(f"\n🎉 DONE! Final video: {FINAL_OUT}")
        state["final"] = FINAL_OUT
        state["done"] = True
        save(state)
    else:
        log("ERROR: Concatenation failed")


if __name__ == "__main__":
    while True:
        try:
            main()
            break  # Success
        except Exception as e:
            log(f"PIPELINE ERROR: {e}")
            import traceback
            log(traceback.format_exc())
            log("Retrying in 120s...")
            time.sleep(120)
