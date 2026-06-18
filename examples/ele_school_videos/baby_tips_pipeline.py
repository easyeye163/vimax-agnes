#!/usr/bin/env python3
"""Process baby tips videos: TTS + concat + merge"""
import json, os, sys, subprocess, asyncio

WORK = "/home/z/my-project/vimax-agnes/.working_dir"
DOWNLOAD = "/home/z/my-project/download"

def log(msg):
    print(f"[{subprocess.check_output('date +%H:%M:%S', shell=True).decode().strip()}] {msg}", flush=True)

os.makedirs(DOWNLOAD, exist_ok=True)
import edge_tts

for ep in ["baby_tips_sleep", "baby_tips_food", "baby_tips_play"]:
    ep_dir = os.path.join(WORK, ep)
    with open(os.path.join(ep_dir, "tts.json")) as f: tts = json.load(f)
    log(f"{ep}: generating TTS...")
    zh_mp3 = os.path.join(ep_dir, "tts_full.mp3")
    asyncio.run(edge_tts.Communicate(tts["zh"], tts["tts_config"]["voice"], rate=tts["tts_config"]["rate"]).save(zh_mp3))
    dur = float(subprocess.check_output(f'ffprobe -v error -show_entries format=duration -of csv=p=0 "{zh_mp3}"', shell=True).strip())
    log(f"{ep}: TTS {dur:.1f}s")
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
    log(f"OUTPUT: {size_mb:.1f}MB -> {out}")
    if size_mb > 10:
        compressed = os.path.join(DOWNLOAD, f"{ep}_hd_land_c.mp4")
        subprocess.run(f'ffmpeg -y -i "{out}" -c:v libx264 -preset ultrafast -crf 35 -c:a copy -movflags +faststart "{compressed}"', shell=True, capture_output=True)
        os.replace(compressed, out)
        log(f"COMPRESSED: {os.path.getsize(out)/(1024*1024):.1f}MB")

log("DONE")
