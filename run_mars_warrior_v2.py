#!/usr/bin/env python3
"""Mars Warrior vs Alien Invaders — Improved ti2vid pipeline.

Improved flow (v2):
1. Generate character reference image
2. For EACH scene, use img2img (with char ref as input) to generate a unique first-frame
   showing the character IN that specific scene context
3. Each scene uses its own unique first-frame for ti2vid

This ensures: character consistency (same ref) + unique scene starts (different first-frames)
Portrait 768x1152, cinematic quality.
"""
import json, requests, time, os, base64, mimetypes, shutil

API_KEY = "sk-IpvltJlHQGKTxzwGn0Eg0tfrscrBVMKrdjdmWc5bofC2DUP0"
BASE_URL = "https://apihub.agnes-ai.com/v1"
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
WD = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".working_dir/mars_warrior_v2")
SF = os.path.join(WD, "state.json")
LF = os.path.join(WD, "pipeline.log")
DL_DIR = "/home/z/my-project/download"
FINAL_OUT = os.path.join(DL_DIR, "mars_warrior_v2.mp4")
W, H, NF, FR = 768, 1152, 241, 24  # Portrait mode

# ===== Character Reference =====
CHAR_REF_PROMPT = """Generate a realistic cinematic portrait of Commander Kaelen "Iron Scar" Vasquez, a 34-year-old Martian Defense Force elite warrior. He has a rugged, battle-hardened face with a prominent vertical scar across his left cheek, short-cropped dark hair with a silver streak on the right temple, and piercing steel-blue eyes that convey both intensity and resolve. His skin is weathered and tanned from prolonged Mars surface exposure. He wears a matte-black combat exoskeleton suit with angular carbon-fiber armor plates, glowing cyan circuit lines running along the shoulders and forearms, and a high-collared tactical vest with mission patches. A holographic tactical visor is pushed up on his forehead. His muscular build fills the armor naturally. The background shows the rust-red Martian terrain with a distant colony dome under an amber sky. Photorealistic film still style, dramatic side lighting, 85mm lens, shallow depth of field, cinematic color grading with teal and orange tones."""

# ===== Per-scene first-frame prompts (img2img with character ref) =====
# Each generates a UNIQUE image of the character in that scene's context
SCENE_FIRST_FRAME_PROMPTS = [
    """A low-angle cinematic shot of Commander Kaelen Vasquez, a rugged warrior with a vertical scar on his left cheek, short dark hair with silver streak, steel-blue eyes, wearing a matte-black combat exoskeleton with glowing cyan circuit lines. He stands alone on a rust-red Martian ridge at dawn, fists clenched at his sides, staring defiantly upward at a massive biomechanical alien mothership descending from the darkening amber sky. Red dust swirls around his boots. His holographic visor glows cyan on his forehead. Dramatic orange and teal color grading, volumetric dust, cinematic film still, 24mm wide-angle lens.""",

    """A tracking shot of Commander Kaelen Vasquez, a rugged warrior with a vertical scar on his left cheek, short dark hair with silver streak, steel-blue eyes, wearing a matte-black combat exoskeleton with glowing cyan circuit lines, sprinting down a narrow metal corridor inside a Mars colony. Emergency red lights flash, casting harsh shadows. He reaches for a heavy plasma rifle mounted on the wall. Scared civilian colonists blur in the background. High contrast red and cyan lighting, frantic action, cinematic film still, 35mm lens, motion blur.""",

    """An epic wide shot of Commander Kaelen Vasquez, a rugged warrior with a vertical scar on his left cheek, short dark hair with silver streak, steel-blue eyes, wearing a matte-black combat exoskeleton with glowing cyan circuit lines, leading a squad of Martian soldiers across an open red dust plain. He raises his plasma rifle and fires a brilliant cyan energy beam. Behind the squad, massive quadrupedal biomechanical alien war machines with glowing violet cores emerge from a breached colony wall. Explosions and debris fill the frame. Blockbuster sci-fi cinematography, teal vs violet contrast, 16mm ultra-wide, deep focus.""",

    """A close-up action shot of Commander Kaelen Vasquez, a rugged warrior with a vertical scar on his left cheek, short dark hair with silver streak, steel-blue eyes, wearing a matte-black combat exoskeleton with glowing cyan circuit lines pulsing brightly, locked in hand-to-hand combat with a towering alien warrior with iridescent chitin armor, four arms wielding crystalline blades, and multifaceted emerald-green glowing eyes. They are inside a shattered glass dome atrium with sparks flying from their clashing weapons. Extreme contrast cyan vs emerald, visceral cinematography, 50mm lens.""",

    """A heroic silhouette shot of Commander Kaelen Vasquez, a rugged warrior with a vertical scar on his left cheek, short dark hair with silver streak, steel-blue eyes, wearing a battered matte-black combat exoskeleton with glowing cyan circuit lines, standing victorious atop a ruined alien war machine. He has removed his helmet, holding it under his arm. The setting Martian sun casts long dramatic golden shadows across the devastated battlefield. Smoldering wreckage and disabled alien drones surround him. Surviving colonists emerge in the background. Golden hour lighting, warm amber and teal palette, 85mm lens, film grain."""
]

# ===== 5 Scene Video Prompts (same story, for ti2vid) =====
SCENES = [
    """Scene 1: A dramatic low-angle shot of Commander Kaelen Vasquez standing alone on a rust-red Martian ridge at dawn, staring at a massive alien mothership descending through the thin amber atmosphere. The ship is biomechanical with pulsating organic membranes and jagged crystalline spires. Wind whips red dust around his boots. His holographic visor activates, casting cyan glow. The camera slowly circles him. Cinematic sci-fi epic, 24mm wide-angle, volumetric dust, orange and teal grading.""",

    """Scene 2: Commander Kaelen Vasquez sprints through a narrow Martian colony corridor. Emergency red lights flash rhythmically. Civilian colonists scramble as alarm sirens wail. He barks orders into a wrist comm and grabs a heavy plasma rifle from a wall rack. Corridor walls are scarred metal with Mars dust on floors. Handheld camera, frantic pace, high contrast, cinematic action style, 35mm lens.""",

    """Scene 3: Commander Kaelen Vasquez leads a squad of six Martian soldiers across an open dust plain toward a breached colony wall. Towering quadrupedal biomechanical alien war machines with glowing violet energy cores emerge from the breach. Kaelen fires a cyan plasma beam illuminating the battlefield. Explosions send debris flying. Camera pulls back revealing the scale. Blockbuster cinematography, 16mm ultra-wide, teal vs violet.""",

    """Scene 4: Commander Kaelen Vasquez in hand-to-hand combat with a towering alien warrior inside a shattered colony atrium. The alien has iridescent chitin armor, four arms with crystalline blades, emerald-green multifaceted eyes. Kaelen's exosuit glows brighter as combat boost activates. Sparks fly from clashing weapons. Glass rains from shattered dome above. 360-degree camera whirl, fast shutter, cyan vs emerald contrast, visceral fight choreography, 50mm lens.""",

    """Scene 5: Commander Kaelen Vasquez stands victorious atop a ruined alien war machine. Setting Martian sun casts long dramatic shadows. Smoldering wreckage and disabled drones litter the red dust. Armor battered but cyan circuits still glow. He removes his helmet, revealing scarred face and steel-blue eyes, breathing heavily. Surviving colonists emerge from damaged dome. Crane shot rises slowly. Golden hour, warm amber and teal, 85mm lens, film grain."""
]


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
            if method == method:
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


def upload_image_to_url(image_path_or_url):
    """Upload an image (file path or URL) and return its URL."""
    if image_path_or_url.startswith(("http://", "https://")):
        return image_path_or_url  # Already a URL

    with open(image_path_or_url, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    mime = mimetypes.guess_type(image_path_or_url)[0] or "image/png"
    uri = f"data:{mime};base64,{b64}"
    result = retry_req("POST", f"{BASE_URL}/images/generations", {
        "model": "agnes-image-2.1-flash",
        "prompt": "exact same image, keep everything unchanged",
        "n": 1, "size": "1024x1024",
        "extra_body": {"response_format": "url", "image": uri}
    }, label=f"upload_img({os.path.basename(image_path_or_url)})")
    return result["data"][0]["url"]


def gen_character_reference():
    """Step 1: Generate character reference image."""
    ref_path = os.path.join(WD, "character_reference.png")
    if os.path.exists(ref_path) and os.path.getsize(ref_path) > 10000:
        log("Character reference already exists")
    else:
        log("Step 1: Generating character reference image...")
        result = retry_req("POST", f"{BASE_URL}/images/generations", {
            "model": "agnes-image-2.1-flash",
            "prompt": CHAR_REF_PROMPT,
            "n": 1,
            "size": "1024x1024"
        }, label="gen_char_ref")
        url = result["data"][0]["url"]
        r = requests.get(url, timeout=120)
        with open(ref_path, "wb") as f:
            f.write(r.content)
        log(f"  Character reference saved ({os.path.getsize(ref_path)//1024}KB)")
    return ref_path


def gen_scene_first_frame(char_ref_path, scene_idx):
    """Step 2: Use img2img to generate a unique first-frame for each scene."""
    ff_path = os.path.join(WD, f"scene_{scene_idx}", "first_frame.png")
    if os.path.exists(ff_path) and os.path.getsize(ff_path) > 10000:
        log(f"  Scene {scene_idx} first-frame already exists")
        return ff_path

    os.makedirs(os.path.dirname(ff_path), exist_ok=True)
    log(f"  Generating first-frame for scene {scene_idx} (img2img)...")

    # Upload char ref to get URL for img2img
    char_url = upload_image_to_url(char_ref_path)

    # Use img2img: character reference as input, scene-specific prompt
    result = retry_req("POST", f"{BASE_URL}/images/generations", {
        "model": "agnes-image-2.0-flash",
        "prompt": SCENE_FIRST_FRAME_PROMPTS[scene_idx],
        "n": 1,
        "size": "1024x1024",
        "extra_body": {"image": char_url}
    }, label=f"gen_ff_s{scene_idx}")

    url = result["data"][0].get("url", "")
    if url:
        r = requests.get(url, timeout=120)
        with open(ff_path, "wb") as f:
            f.write(r.content)
        log(f"  Scene {scene_idx} first-frame saved ({os.path.getsize(ff_path)//1024}KB)")
    else:
        log(f"  Scene {scene_idx} first-frame generation failed!")
    return ff_path


def submit_ti2vid(prompt, img_url):
    """Submit image-to-video."""
    payload = {
        "model": "agnes-video-v2.0",
        "prompt": prompt,
        "width": W, "height": H, "num_frames": NF, "frame_rate": FR,
        "image": img_url, "mode": "ti2vid",
    }
    result = retry_req("POST", f"{BASE_URL}/videos", payload, label="submit_ti2vid")
    tid = result.get("task_id") or result.get("id")
    log(f"  TI2VID submitted: {tid[:30]}...")
    return tid


def main():
    os.makedirs(WD, exist_ok=True)

    state = load()
    n = len(SCENES)
    log(f"MARS WARRIOR V2 — {n} scenes, {W}x{H}, portrait, cinematic")
    log(f"Flow: char ref -> img2img per-scene first-frames -> ti2vid")
    log(f"IMPROVEMENT: Each scene gets a unique first-frame from char ref")

    # Save script
    with open(f"{WD}/script.json", "w") as f:
        json.dump(SCENES, f, ensure_ascii=False, indent=2)
    with open(f"{WD}/ff_prompts.json", "w") as f:
        json.dump(SCENE_FIRST_FRAME_PROMPTS, f, ensure_ascii=False, indent=2)

    # Step 1: Generate character reference
    char_ref_path = gen_character_reference()

    # Step 2: Generate unique first-frame for each scene
    for si in range(n):
        if not state.get(f"s{si}_task"):  # Only if not already submitted
            log(f"\n--- Scene {si} first-frame ---")
            ff_path = gen_scene_first_frame(char_ref_path, si)
            state[f"s{si}_ff"] = ff_path
            save(state)

    # Step 3: Upload first-frames and submit ti2vid for each scene
    for si in range(n):
        sd = os.path.join(WD, f"scene_{si}")
        vp = os.path.join(sd, "video.mp4")
        os.makedirs(sd, exist_ok=True)

        if os.path.exists(vp) and os.path.getsize(vp) > 10000:
            log(f"Scene {si}: video exists ({os.path.getsize(vp)//1024}KB), skip")
            continue

        etid = state.get(f"s{si}_task")
        if etid:
            log(f"Scene {si}: already submitted: {etid[:20]}...")
            continue

        # Upload this scene's first-frame
        ff_path = os.path.join(WD, f"scene_{si}", "first_frame.png")
        if not (os.path.exists(ff_path) and os.path.getsize(ff_path) > 10000):
            log(f"Scene {si}: first-frame missing! Generating...")
            gen_scene_first_frame(char_ref_path, si)

        log(f"\nSubmitting Scene {si}/{n-1} (unique first-frame)...")
        ff_url = upload_image_to_url(ff_path)
        tid = submit_ti2vid(SCENES[si], ff_url)
        state[f"s{si}_task"] = tid
        state[f"s{si}_ff_url"] = ff_url
        save(state)
        log(f"Scene {si}: task queued")
        time.sleep(5)

    log(f"\nAll {n} scenes submitted. Use poll_mars_warrior_v2.py to check progress.")


if __name__ == "__main__":
    main()
