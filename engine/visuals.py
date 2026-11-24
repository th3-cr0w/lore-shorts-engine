"""Turn each script line into a graded 9:16 shot of exactly the right length."""
import os
import subprocess

W, H, FPS = 1080, 1920, 30
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}

# One look for every shot: darker, less saturated, vignette, light grain.
GRADE = ("eq=contrast=1.12:saturation=0.82:brightness=-0.03,"
         "vignette=angle=PI/4.5,noise=alls=4:allf=t,format=yuv420p")

# Stand-in looks per shot type, used only until real assets are gathered.
PLACEHOLDER = {
    "STOCK": ("0x1a0703", "colorbalance=rs=.35:gs=.02:bs=-.30"),
    "AI": ("0x0b0717", "colorbalance=rs=.05:gs=-.05:bs=.30"),
    "SIL": ("0x06101a", "colorbalance=rs=-.15:gs=.0:bs=.25"),
    "TEXT": ("0x080808", "colorbalance=rs=.05:gs=.02:bs=-.02"),
    "ART": ("0x140f08", "colorbalance=rs=.15:gs=.08:bs=-.10"),
}


def tuple_ext():
    return tuple(IMAGE_EXT)


def _run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.PIPE)


def _escape_drawtext(text):
    return (text.replace("\\", "\\\\").replace(":", "\\:")
            .replace("'", "’").replace("%", "\\%"))


def _encode_args(frames, out):
    return ["-frames:v", str(frames), "-r", str(FPS), "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", out]


def build_shot(line, duration, out, font_file, zoom_in=True, motion="push"):
    """Render one shot. Returns the number of frames written.

    Stills get 2.5D parallax (motion: push, drift_left, drift_right, rise),
    or a flat slow zoom if the line sets "motion": "kenburns"."""
    frames = max(int(round(duration * FPS)), 1)
    asset = line.get("asset")
    motion = line.get("motion", motion)
    if (asset and os.path.exists(asset)
            and os.path.splitext(asset)[1].lower() in IMAGE_EXT
            and motion != "kenburns"):
        from . import parallax
        written, source = parallax.render(asset, duration, out, GRADE,
                                          motion=motion)
        line["_depth_source"] = source
        return written
    z_end = 1.07
    z_expr = (f"1+{z_end - 1}*on/{frames}" if zoom_in
              else f"{z_end}-{z_end - 1}*on/{frames}")
    zoom = (f"zoompan=z='{z_expr}':x='iw/2-(iw/zoom/2)':"
            f"y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS}")

    if asset and os.path.exists(asset):
        ext = os.path.splitext(asset)[1].lower()
        if ext in IMAGE_EXT:
            src = ["-loop", "1", "-i", asset]
            # Scale up first so the slow zoom stays smooth on stills.
            vf = (f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,"
                  f"crop={W * 2}:{H * 2},{zoom},{GRADE}")
        else:
            src = ["-stream_loop", "-1", "-i", asset]
            vf = (f"fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase,"
                  f"crop={W}:{H},{zoom},{GRADE}")
        _run(["ffmpeg", "-y", "-v", "error", *src, "-vf", vf,
              *_encode_args(frames, out)])
        return frames

    # Placeholder: a moving, flickering texture in the shot type's colour,
    # labelled with what the real footage should be.
    shot = line.get("shot", "STOCK").upper()
    color, tint = PLACEHOLDER.get(shot, PLACEHOLDER["STOCK"])
    query = ", ".join(line.get("query", [])) or line.get("on_screen", "")
    label = _escape_drawtext(f"PLACEHOLDER  {shot}: {query}"[:60])
    vf = (f"noise=alls=70:allf=t+u,gblur=sigma=18,"
          f"eq=brightness='0.05*sin(2*PI*t*0.9)':eval=frame,{tint},"
          f"scale={W}:{H},{zoom},{GRADE},"
          f"drawtext=fontfile={font_file}:text='{label}':fontsize=30:"
          f"fontcolor=white@0.45:x=(w-tw)/2:y=h*0.14")
    _run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
          f"color=c={color}:s={W // 2}x{H // 2}:r={FPS}",
          "-vf", vf, *_encode_args(frames, out)])
    return frames


def build_end_card(duration, out):
    frames = max(int(round(duration * FPS)), 1)
    _run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
          f"color=c=0x050505:s={W}x{H}:r={FPS}",
          "-vf", f"vignette=angle=PI/4,noise=alls=5:allf=t,format=yuv420p",
          *_encode_args(frames, out)])
    return frames


def concat(paths, out, workdir):
    list_file = os.path.join(workdir, "shots.txt")
    with open(list_file, "w") as fh:
        for p in paths:
            fh.write(f"file '{os.path.abspath(p)}'\n")
    _run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
          "-i", list_file, "-c", "copy", out])
