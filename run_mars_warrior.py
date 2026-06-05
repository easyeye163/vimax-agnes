#!/usr/bin/env python3
"""Mars Warrior vs Alien Invaders — 5-scene ti2vid + character reference pipeline.
Best consistency flow: generate character reference image FIRST, then ti2vid all scenes with it.
Portrait 768x1152, cinematic quality.
"""
import json, requests, time, os, base64, mimetypes, shutil

API_KEY = "sk-IpvltJlHQGKTxzwGn0Eg0tfrscrBVMKrdjdmWc5bofC2DUP0"
BASE_URL = "https://apihub.agnes-ai.com/v1"
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
WD = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".working_dir/mars_warrior")
SF = os.path.join(WD, "state.json")
LF = os.path.join(WD, "pipeline.log")
DL_DIR = "/home/z/my-project/download"
FINAL_OUT = os.path.join(DL_DIR, "mars_warrior.mp4")
W, H, NF, FR = 768, 1152, 241, 24  # Portrait mode

# ===== Character Reference =====
CHAR_REF_PROMPT = """Generate a realistic cinematic portrait of Commander Kaelen "Iron Scar" Vasquez, a 34-year-old Martian Defense Force elite warrior. He has a rugged, battle-hardened face with a prominent vertical scar across his left cheek, short-cropped dark hair with a silver streak on the right temple, and piercing steel-blue eyes that convey both intensity and resolve. His skin is weathered and tanned from prolonged Mars surface exposure. He wears a matte-black combat exoskeleton suit with angular carbon-fiber armor plates, glowing cyan circuit lines running along the shoulders and forearms, and a high-collared tactical vest with mission patches. A holographic tactical visor is pushed up on his forehead. His muscular build fills the armor naturally. The background shows the rust-red Martian terrain with a distant colony dome under an amber sky. Photorealistic film still style, dramatic side lighting, 85mm lens, shallow depth of field, cinematic color grading with teal and orange tones."""

# ===== 5 Scene Prompts (all include character description for consistency) =====
CHAR_DESC = (
    "Commander Kaelen Vasquez, a 34-year-old rugged warrior with a vertical scar on his left cheek, "
    "short-cropped dark hair with a silver streak, piercing steel-blue eyes, wearing a matte-black "
    "combat exoskeleton suit with angular carbon-fiber armor plates, glowing cyan circuit lines on "
    "shoulders and forearms, and a high-collared tactical vest"
)

SCENES = [
    f"""Scene 1: A dramatic low-angle shot of {CHAR_DESC}. He stands alone on a rust-red Martian ridge at dawn, staring at a massive alien mothership descending through the thin amber atmosphere. The ship is biomechanical in design, with pulsating organic membranes and jagged crystalline spires. Wind whips red dust around his boots as he clenches his fists. His holographic visor activates on his forehead, casting a cyan glow on his face. The sky behind the alien ship darkens ominously. The camera slowly circles around him, emphasizing his isolation against the overwhelming threat. Shot on 24mm wide-angle lens, deep depth of field, cinematic sci-fi epic style, dramatic orange and teal color grading, volumetric dust particles.""",

    f"""Scene 2: An intense medium tracking shot of {CHAR_DESC} sprinting through a narrow Martian colony corridor. Emergency red lights flash rhythmically, casting harsh shadows. Civilian colonists scramble in the background as alarm sirens wail. Kaelen barks orders into a wrist comm, his scar catching the strobing light. He grabs a heavy plasma rifle from a wall rack without breaking stride. The corridor walls are scarred metal panels with Mars regolith dust coating the floors. The camera follows his determined movement from a slight low angle, emphasizing his urgency and leadership. Shot on 35mm lens, medium depth of field, handheld camera feel, high contrast lighting, frantic pace, cinematic action style.""",

    f"""Scene 3: A breathtaking wide shot of {CHAR_DESC} leading a squad of six Martian soldiers across an open dust plain toward a breached colony wall. Behind them, towering alien war machines emerge from the breach — massive quadrupedal biomechanical creatures with glowing violet energy cores and tentacle-like appendages. The alien footfalls send shockwaves through the red soil. Kaelen raises his plasma rifle and fires a brilliant cyan beam that illuminates the entire battlefield. Explosions rock the ground, sending debris flying. The camera pulls back dramatically to reveal the scale of the confrontation. Shot on 16mm ultra-wide lens, epic deep focus, blockbuster sci-fi cinematography, high dynamic range, intense teal versus violet color contrast.""",

    f"""Scene 4: A tight close-up action sequence of {CHAR_DESC} in hand-to-hand combat with a towering alien warrior inside a shattered colony atrium. The alien has iridescent chitin armor, four arms wielding crystalline blades, and multifaceted eyes glowing emerald green. Kaelen's exosuit glows brighter as he activates his combat boost, cyan circuits pulsing intensely. Sparks fly as their weapons clash. Glass from the shattered dome above rains down, catching the light of distant explosions outside. Kaelen dodges a sweeping blade strike and counters with an energy-empowered punch. The camera whirls around the combat in a continuous 360-degree shot, capturing every devastating exchange. Shot on 50mm lens, fast shutter speed, dynamic motion blur, visceral cinematic fight choreography, extreme contrast between cyan human tech and emerald alien bio-armor.""",

    f"""Scene 5: A heroic slow-motion silhouette shot of {CHAR_DESC} standing victorious atop a ruined alien war machine. The setting Martian sun casts long dramatic shadows across the devastated but quiet battlefield. Smoldering wreckage and disabled alien drones litter the red dust around him. His armor is battered and scorched but his cyan circuits still glow. He removes his helmet, revealing his scarred face and steel-blue eyes, breathing heavily but standing tall. In the background, a few surviving colonists emerge from the damaged dome, their faces illuminated by the warm amber sunset. Kaelen turns to face them with a look of exhausted triumph. The camera slowly rises on a crane shot, pulling back to show the full panorama of the scarred Martian landscape and the distant colony. Shot on 85mm lens, golden hour lighting, shallow depth of field, triumphant cinematic epic style, warm amber and cool teal color palette, film grain texture."""
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


def gen_character_reference():
    """Generate character reference image and return its URL."""
    ref_path = os.path.join(WD, "character_reference.png")
    if os.path.exists(ref_path) and os.path.getsize(ref_path) > 10000:
        log("Character reference already exists, uploading...")
    else:
        log("Generating character reference image...")
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

    # Upload to get a URL for ti2vid
    with open(ref_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    mime = mimetypes.guess_type(ref_path)[0] or "image/png"
    uri = f"data:{mime};base64,{b64}"
    result = retry_req("POST", f"{BASE_URL}/images/generations", {
        "model": "agnes-image-2.1-flash",
        "prompt": "exact same image, keep everything unchanged",
        "n": 1, "size": "1024x1024",
        "extra_body": {"response_format": "url", "image": uri}
    }, label="upload_char_ref")
    char_url = result["data"][0]["url"]
    log(f"  Character reference URL: {char_url[:60]}...")
    return char_url


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
    log(f"MARS WARRIOR — {n} scenes, {W}x{H}, portrait, cinematic")
    log(f"Flow: ti2vid + character reference (best consistency)")

    # Save script
    with open(f"{WD}/script.json", "w") as f:
        json.dump(SCENES, f, ensure_ascii=False, indent=2)
    with open(f"{WD}/char_ref_prompt.txt", "w") as f:
        f.write(CHAR_REF_PROMPT)

    # Step 1: Generate character reference
    if not state.get("char_url"):
        char_url = gen_character_reference()
        state["char_url"] = char_url
        save(state)
    else:
        char_url = state["char_url"]
        log("Using existing character reference URL")

    # Step 2: Submit all 5 scenes as ti2vid
    for si in range(n):
        sd = os.path.join(WD, f"scene_{si}")
        vp = os.path.join(sd, "video.mp4")
        os.makedirs(sd, exist_ok=True)

        if os.path.exists(vp) and os.path.getsize(vp) > 10000:
            log(f"Scene {si}: exists ({os.path.getsize(vp)//1024}KB), skip")
            continue

        # Check existing task
        etid = state.get(f"s{si}_task")
        if etid:
            log(f"Scene {si}: task already submitted: {etid[:20]}...")
            continue

        log(f"\nSubmitting Scene {si}/{n-1}...")
        tid = submit_ti2vid(SCENES[si], char_url)
        state[f"s{si}_task"] = tid
        save(state)
        log(f"Scene {si}: task queued")
        time.sleep(5)  # Brief pause between submissions

    log(f"\nAll {n} scenes submitted. Use poll_mars_warrior.py to check progress.")


if __name__ == "__main__":
    main()
