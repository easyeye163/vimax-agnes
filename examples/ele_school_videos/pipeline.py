#!/usr/bin/env python3
"""
小学生教育视频生成流水线

功能:
  1. 从 prompts.json 读取图片生成提示词，生成首帧图片
  2. 将首帧图片转为JPEG（降低payload体积），提交图生视频任务
  3. 轮询视频任务状态，下载完成的视频
  4. 生成连续中文TTS配音（edge-tts），与视频合并
  5. 拼接所有场景，压缩输出

关键设计决策:
  - PNG→JPEG优化: ffmpeg -q:v 5 可将1.6MB降至163KB，避免API超时
  - POST timeout=180s: 视频提交需要较长超时
  - 连续TTS配音: 整集一条叙述，不按场景分段，避免每5秒断开
  - TTS时长控制: 文案长度需匹配视频时长（40s），中文约35-39秒为佳
  - 并行提交: ThreadPoolExecutor(max_workers=6)加速24个场景的提交
  - 压缩策略: 优先 -c copy -movflags +faststart（无损），超10MB则重编码CRF 35

API:
  - 图片生成: POST /v1/images/generations (model: agnes-image-2.1-flash)
  - 视频生成: POST /v1/videos (model: agnes-video-v2.0, 含image base64)
  - 视频轮询: GET /v1/videos/{task_id}
  - 视频URL: response.remixed_from_video_id
"""

import json, os, sys, time, base64, subprocess, requests, asyncio, shutil
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============ 配置 ============
API = "https://apihub.agnes-ai.com/v1"
KEY = "your-api-key-here"  # 替换为你的API Key
HEADERS = {"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"}

# 工作目录（存放中间文件）和输出目录
WORK_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(WORK_DIR, "..", "..", "output")

# 集数配置: (目录名, prompts文件, tts文件)
EPISODES = [
    ("ele_math", "ele_math/prompts.json", "ele_math/tts.json"),
    ("ele_science", "ele_science/prompts.json", "ele_science/tts.json"),
    ("ele_nature", "ele_nature/prompts.json", "ele_nature/tts.json"),
]

SCENES_PER_EP = 8
VIDEO_SIZE = "1280x720"
IMAGE_SIZE = "1280x720"

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ============ 阶段1: 生成首帧图片 ============
def gen_frames(ep_name, prompts_file):
    """从提示词生成首帧图片（PNG）"""
    prompts_path = os.path.join(WORK_DIR, prompts_file)
    with open(prompts_path) as f:
        prompts = json.load(f)["prompts"]

    for i, prompt in enumerate(prompts):
        out_dir = os.path.join(WORK_DIR, ep_name, "scenes", f"scene_{i}")
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, "first_frame.png")
        if os.path.exists(out) and os.path.getsize(out) > 10000:
            log(f"  SKIP {ep_name}/scene_{i} (exists)")
            continue
        for attempt in range(3):
            try:
                r = requests.post(f"{API}/images/generations", headers=HEADERS, json={
                    "model": "agnes-image-2.1-flash",
                    "prompt": prompt,
                    "size": IMAGE_SIZE,
                    "n": 1
                }, timeout=60)
                if r.status_code == 200:
                    url = r.json()["data"][0]["url"]
                    img = requests.get(url, timeout=60)
                    with open(out, "wb") as f:
                        f.write(img.content)
                    log(f"  OK {ep_name}/scene_{i} ({len(img.content)//1024}KB)")
                    break
                else:
                    log(f"  ERR {ep_name}/scene_{i}: status={r.status_code}")
            except Exception as e:
                log(f"  RETRY {ep_name}/scene_{i}: {e}")
                time.sleep(5)


# ============ 阶段2: 提交视频任务 ============
def submit_one(ep_name, prompts_file, i):
    """提交单个场景的视频生成任务（PNG→JPEG→base64→POST）"""
    prompts_path = os.path.join(WORK_DIR, prompts_file)
    img_path = os.path.join(WORK_DIR, ep_name, "scenes", f"scene_{i}", "first_frame.png")
    video_path = os.path.join(WORK_DIR, ep_name, "scenes", f"scene_{i}", "video.mp4")

    # 跳过已下载的
    if os.path.exists(video_path) and os.path.getsize(video_path) > 50000:
        return (ep_name, i, None)

    if not os.path.exists(img_path):
        return (ep_name, i, None)

    # ★ 关键优化: PNG→JPEG降低payload（1.6MB→163KB）
    jpg_path = f"/tmp/{ep_name}_{i}.jpg"
    subprocess.run(
        f'ffmpeg -y -i "{img_path}" -q:v 5 "{jpg_path}"',
        shell=True, capture_output=True
    )
    with open(jpg_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    with open(prompts_path) as f:
        prompts = json.load(f)["prompts"]

    # ★ POST timeout=180s（视频生成提交需要较长超时）
    for attempt in range(3):
        try:
            r = requests.post(f"{API}/videos", headers=HEADERS, json={
                "model": "agnes-video-v2.0",
                "prompt": prompts[i][:300],  # 截断到300字符
                "image": b64,
                "size": VIDEO_SIZE
            }, timeout=180)
            if r.status_code == 200:
                tid = r.json()["id"]
                log(f"  SUBMITTED {ep_name}/scene_{i}: {tid}")
                return (ep_name, i, tid)
            else:
                log(f"  ERR {ep_name}/scene_{i}: {r.status_code}")
                return (ep_name, i, None)
        except Exception as e:
            log(f"  RETRY {ep_name}/scene_{i}: {e}")
            time.sleep(5)
    return (ep_name, i, None)


def submit_all():
    """并行提交所有场景的视频任务"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    all_results = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {}
        for ep_name, prompts_file, _ in EPISODES:
            for i in range(SCENES_PER_EP):
                f = pool.submit(submit_one, ep_name, prompts_file, i)
                futures[f] = (ep_name, i)
        for f in as_completed(futures):
            ep_name, i, tid = f.result()
            all_results[(ep_name, i)] = tid

    # 保存task_ids
    for ep_name, _, _ in EPISODES:
        task_ids = [all_results.get((ep_name, i)) for i in range(SCENES_PER_EP)]
        tid_file = os.path.join(WORK_DIR, ep_name, "task_ids.json")
        with open(tid_file, "w") as f:
            json.dump(task_ids, f)
        submitted = sum(1 for t in task_ids if t)
        log(f"  {ep_name}: {submitted}/{SCENES_PER_EP} submitted")


# ============ 阶段3: 轮询下载 ============
def poll_and_download(ep_name):
    """轮询视频任务，下载已完成的视频"""
    tid_file = os.path.join(WORK_DIR, ep_name, "task_ids.json")
    if not os.path.exists(tid_file):
        return False

    with open(tid_file) as f:
        task_ids = json.load(f)

    all_done = True
    for i, tid in enumerate(task_ids):
        if not tid:
            continue
        video_path = os.path.join(WORK_DIR, ep_name, "scenes", f"scene_{i}", "video.mp4")
        if os.path.exists(video_path) and os.path.getsize(video_path) > 50000:
            continue
        try:
            r = requests.get(f"{API}/videos/{tid}", headers=HEADERS, timeout=30)
            data = r.json()
            status = data.get("status", "unknown")
            # ★ 视频URL字段: remixed_from_video_id
            if status == "completed" and data.get("remixed_from_video_id"):
                url = data["remixed_from_video_id"]
                vr = requests.get(url, timeout=120)
                with open(video_path, "wb") as f:
                    f.write(vr.content)
                log(f"  DOWNLOADED {ep_name}/scene_{i} ({len(vr.content)//1024}KB)")
            elif status in ("queued", "in_progress"):
                progress = data.get("progress", 0)
                log(f"  PENDING {ep_name}/scene_{i}: {status} {progress}%")
                all_done = False
            elif status == "failed":
                log(f"  FAILED {ep_name}/scene_{i}")
        except Exception as e:
            log(f"  POLL_ERR {ep_name}/scene_{i}: {e}")
            all_done = False
    return all_done


# ============ 阶段4: TTS配音 + 拼接 + 压缩 ============
def process_episode(ep_name, tts_file):
    """
    TTS配音 + 合并视频音频 + 拼接场景 + 压缩输出

    ★ 关键设计: 连续中文配音，不按场景分段
    - 整集一条叙述，保持流畅
    - TTS时长控制在视频时长的85-95%（留1-2秒自然结尾）
    - edge-tts生成，ffmpeg合并
    """
    try:
        import edge_tts
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "edge_tts", "-q"], check=True)
        import edge_tts

    tts_path = os.path.join(WORK_DIR, tts_file)
    with open(tts_path) as f:
        tts_data = json.load(f)

    narration = tts_data["narration"]
    voice = tts_data["tts_config"]["voice"]
    rate = tts_data["tts_config"]["rate"]

    log(f"Processing {ep_name}...")

    # 生成连续TTS
    zh_mp3 = os.path.join(WORK_DIR, ep_name, "tts_full.mp3")
    asyncio.run(edge_tts.Communicate(narration, voice, rate=rate).save(zh_mp3))

    dur = float(subprocess.check_output(
        f'ffprobe -v error -show_entries format=duration -of csv=p=0 "{zh_mp3}"',
        shell=True
    ).strip())
    log(f"  TTS duration: {dur:.1f}s")

    # 填充到略长于视频时长（防止音频短于视频）
    padded_mp3 = os.path.join(WORK_DIR, ep_name, "tts_padded.mp3")
    subprocess.run(
        f'ffmpeg -y -i "{zh_mp3}" -af "apad=whole_dur=41" -c:a libmp3lame -q:a 4 "{padded_mp3}"',
        shell=True, capture_output=True
    )

    # 拼接所有场景视频（无音频）
    concat_file = os.path.join(WORK_DIR, ep_name, "concat_list.txt")
    with open(concat_file, "w") as f:
        for i in range(SCENES_PER_EP):
            vp = os.path.join(WORK_DIR, ep_name, "scenes", f"scene_{i}", "video.mp4")
            if os.path.exists(vp) and os.path.getsize(vp) > 50000:
                f.write(f"file '{vp}'\n")

    video_only = os.path.join(WORK_DIR, ep_name, "concat_video.mp4")
    subprocess.run(
        f'ffmpeg -y -f concat -safe 0 -i "{concat_file}" -c copy "{video_only}"',
        shell=True, capture_output=True
    )

    # 合并视频 + 连续配音
    out = os.path.join(OUTPUT_DIR, f"{ep_name}_hd_land.mp4")
    subprocess.run(
        f'ffmpeg -y -i "{video_only}" -i "{padded_mp3}" '
        f'-c:v copy -c:a aac -b:a 128k '
        f'-map 0:v -map 1:a -shortest "{out}"',
        shell=True, capture_output=True
    )

    size_mb = os.path.getsize(out) / (1024 * 1024)
    log(f"  OUTPUT: {size_mb:.1f}MB -> {out}")
    return out


# ============ 主流程 ============
if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "all"

    if phase in ("frames", "all"):
        for ep_name, prompts_file, _ in EPISODES:
            log(f"=== Generating frames: {ep_name} ===")
            gen_frames(ep_name, prompts_file)

    if phase in ("submit", "all"):
        log("=== Submitting all videos ===")
        submit_all()

    if phase in ("poll", "all"):
        for ep_name, _, _ in EPISODES:
            log(f"=== Polling: {ep_name} ===")
            poll_and_download(ep_name)

    if phase in ("process", "all"):
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        for ep_name, _, tts_file in EPISODES:
            log(f"=== Processing: {ep_name} ===")
            try:
                process_episode(ep_name, tts_file)
            except Exception as e:
                log(f"  ERROR {ep_name}: {e}")
