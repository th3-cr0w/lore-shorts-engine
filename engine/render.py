"""Cut one short: voice + render spec in, finished 9:16 video and QA report out.

Usage:
  python -m engine.render --spec specs/W1-1.json --voice W1-1.m4a --out out/W1-1.mp4
"""
import argparse
import json
import os
import subprocess

from . import align as aligner
from . import captions, parallax, visuals

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_DIR = os.path.join(ROOT, "fonts")
FONT_FILE = os.path.join(FONT_DIR, "Anton-Regular.ttf")
FONT_NAME = "Anton"
END_CARD_SECONDS = 1.6


ART_DIR = os.path.join(ROOT, "assets", "art")


def resolve_asset(line):
    """An ART line names an Art bank ID (e.g. A007); use its downloaded file."""
    if line.get("asset") or not line.get("art_id"):
        return
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        path = os.path.join(ART_DIR, line["art_id"] + ext)
        if os.path.exists(path):
            line["asset"] = path
            return


def mix_and_burn(video, voice, ass_path, total, out, music=None):
    """Burn captions, level the voice, add a sound bed that ducks under it."""
    inputs = ["-i", video, "-i", voice]
    if music:
        inputs += ["-stream_loop", "-1", "-i", music]
        bed_src = "[2:a]aformat=sample_rates=48000:channel_layouts=stereo,volume=0.35[bedraw];"
    else:
        # Low dark drone so the test has a bed; real tracks go in assets/music.
        bed_src = (f"anoisesrc=color=brown:amplitude=0.6:r=48000:d={total},"
                   "lowpass=f=160,aformat=channel_layouts=stereo[n];"
                   f"sine=frequency=55:sample_rate=48000:d={total},volume=0.5,"
                   "aformat=channel_layouts=stereo[s];"
                   "[n][s]amix=inputs=2:normalize=0,volume=0.30[bedraw];")
    graph = (
        f"[0:v]ass={ass_path}:fontsdir={FONT_DIR}[v];"
        "[1:a]aformat=sample_rates=48000:channel_layouts=stereo,"
        "highpass=f=80,loudnorm=I=-14:TP=-1.5:LRA=11,apad[voice];"
        "[voice]asplit=2[vmix][vkey];"
        f"{bed_src}"
        f"[bedraw]atrim=0:{total},afade=t=out:st={total - 0.8}:d=0.8[bed];"
        "[bed][vkey]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=350[ducked];"
        f"[vmix][ducked]amix=inputs=2:duration=longest:normalize=0,"
        f"atrim=0:{total}[a]"
    )
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", graph,
         "-map", "[v]", "-map", "[a]", "-t", f"{total}",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
         "-maxrate", "8M", "-bufsize", "16M",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
         "-movflags", "+faststart", out],
        check=True, stderr=subprocess.PIPE)


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,width,height", "-of", "json", path],
        capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def qa(out_path, alignment, spec, chunk_count):
    info = probe(out_path)
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    duration = float(info["format"]["duration"])
    short_lines = [i + 1 for i, l in enumerate(alignment["lines"])
                   if l["end"] - l["start"] < 0.6]
    checks = {
        "vertical_1080x1920": video.get("width") == 1080 and video.get("height") == 1920,
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
        "length_15_to_90s": 15 <= duration <= 90,
        "voice_matches_script": (alignment["match_ratio"] is None
                                 or alignment["match_ratio"] >= 0.6),
        "no_shot_under_0.6s": not short_lines,
        "all_assets_real": all(l.get("asset") and os.path.exists(l["asset"])
                               for l in spec["lines"]),
    }
    return {
        "id": spec.get("id"),
        "passed": all(v for k, v in checks.items() if k != "all_assets_real"),
        "checks": checks,
        "duration_s": round(duration, 2),
        "aligner": alignment["backend"],
        "script_words_heard": alignment["match_ratio"],
        "caption_chunks": chunk_count,
        "short_lines": short_lines,
        "depth_sources": sorted({l["_depth_source"] for l in spec["lines"]
                                 if l.get("_depth_source")}),
    }


def render(spec_path, voice_path, out_path, workdir=None, backend="auto",
           music=None):
    with open(spec_path, encoding="utf-8") as fh:
        spec = json.load(fh)
    short_id = spec.get("id", "short")
    workdir = workdir or os.path.join("work", short_id)
    os.makedirs(workdir, exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    script_lines = [l["text"] for l in spec["lines"]]
    alignment = aligner.align(script_lines, voice_path, workdir, backend)
    with open(os.path.join(workdir, "alignment.json"), "w") as fh:
        json.dump(alignment, fh, indent=1)

    shot_paths = []
    still_count = 0
    for i, (line, seg) in enumerate(zip(spec["lines"], alignment["lines"])):
        resolve_asset(line)
        path = os.path.join(workdir, f"shot_{i:02d}.mp4")
        motion = parallax.CYCLE[still_count % len(parallax.CYCLE)]
        if line.get("asset", "").lower().endswith(visuals.tuple_ext()):
            still_count += 1
        visuals.build_shot(line, seg["end"] - seg["start"], path, FONT_FILE,
                           zoom_in=(i % 2 == 0), motion=motion)
        shot_paths.append(path)
    end_path = os.path.join(workdir, "shot_end.mp4")
    visuals.build_end_card(END_CARD_SECONDS, end_path)
    shot_paths.append(end_path)

    joined = os.path.join(workdir, "joined.mp4")
    visuals.concat(shot_paths, joined, workdir)

    total = round(alignment["duration"] + END_CARD_SECONDS, 3)
    ass_path = os.path.join(workdir, "captions.ass")
    chunk_count = captions.build(alignment, spec, script_lines, total,
                                 ass_path, FONT_NAME)

    mix_and_burn(joined, voice_path, ass_path, total, out_path, music)

    report = qa(out_path, alignment, spec, chunk_count)
    with open(os.path.splitext(out_path)[0] + ".qa.json", "w") as fh:
        json.dump(report, fh, indent=1)
    return report


def main():
    p = argparse.ArgumentParser(description="Cut one lore short.")
    p.add_argument("--spec", required=True)
    p.add_argument("--voice", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--workdir")
    p.add_argument("--backend", default="auto",
                   choices=["auto", "whisper", "pauses"])
    p.add_argument("--music")
    a = p.parse_args()
    report = render(a.spec, a.voice, a.out, a.workdir, a.backend, a.music)
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
