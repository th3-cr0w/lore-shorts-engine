"""2.5D parallax for still artwork.

Estimates a depth map for the image, then moves a virtual camera so near
parts shift and grow more than far parts. Works on CPU.

Depth sources, in order:
  1. a cached depth map next to the image: <image>.depth.png (white = near)
  2. Depth Anything V2 Small (Apache-2.0) via transformers, cached after use
  3. a rough heuristic (lower and brighter = nearer) if the model is missing
"""
import os
import subprocess

import cv2
import numpy as np

W, H, FPS = 1080, 1920, 30
MODEL_ID = "depth-anything/Depth-Anything-V2-Small-hf"

# Camera moves. zoom: extra zoom for the nearest layer by the end.
# shift: how far (px) near and far layers separate sideways / vertically.
PRESETS = {
    "push":        {"zoom": 0.10, "sx": 0,   "sy": 0},
    "drift_left":  {"zoom": 0.04, "sx": 70,  "sy": 0},
    "drift_right": {"zoom": 0.04, "sx": -70, "sy": 0},
    "rise":        {"zoom": 0.05, "sx": 0,   "sy": 60},
}
CYCLE = ["push", "drift_left", "rise", "drift_right"]

_pipe = None


def _model_depth(rgb):
    global _pipe
    from PIL import Image
    if _pipe is None:
        from transformers import pipeline
        _pipe = pipeline("depth-estimation", model=MODEL_ID, device=-1)
    out = _pipe(Image.fromarray(rgb))["depth"]  # brighter = nearer
    return np.asarray(out, dtype=np.float32)


def _heuristic_depth(rgb):
    h, w = rgb.shape[:2]
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    gray = cv2.GaussianBlur(gray, (0, 0), sigmaX=w / 40)
    vertical = np.linspace(0, 1, h, dtype=np.float32)[:, None].repeat(w, 1)
    lum = (gray - gray.min()) / max(gray.max() - gray.min(), 1e-6)
    return 0.7 * vertical + 0.3 * lum


def load_depth(image_path, rgb):
    """Return (depth 0..1 with 1 = near, source name)."""
    cached = os.path.splitext(image_path)[0] + ".depth.png"
    if os.path.exists(cached):
        d = cv2.imread(cached, cv2.IMREAD_GRAYSCALE).astype(np.float32)
        source = "cached"
    else:
        try:
            d = _model_depth(rgb)
            source = "depth-anything-v2-small"
        except Exception as exc:  # model not installed or not downloadable
            print(f"[parallax] depth model unavailable ({type(exc).__name__}),"
                  " using heuristic depth")
            d = _heuristic_depth(rgb)
            source = "heuristic"
        d = cv2.resize(d, (rgb.shape[1], rgb.shape[0]))
        norm = (d - d.min()) / max(d.max() - d.min(), 1e-6)
        if source != "heuristic":  # only cache real depth
            cv2.imwrite(cached, (norm * 255).astype(np.uint8))
        d = norm * 255
    d = cv2.resize(d, (rgb.shape[1], rgb.shape[0])) / 255.0
    # Soften and slightly grow near regions so edges stretch instead of tear.
    d = cv2.dilate(d, np.ones((9, 9), np.uint8))
    d = cv2.GaussianBlur(d, (0, 0), sigmaX=max(rgb.shape[1] / 300, 2))
    return d.astype(np.float32), source


def _cover(rgb, w, h):
    ih, iw = rgb.shape[:2]
    scale = max(w / iw, h / ih)
    resized = cv2.resize(rgb, (int(np.ceil(iw * scale)), int(np.ceil(ih * scale))),
                         interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
    y0 = (resized.shape[0] - h) // 2
    x0 = (resized.shape[1] - w) // 2
    return resized[y0:y0 + h, x0:x0 + w]


def render(image_path, duration, out, grade, motion="push", strength=1.0):
    """Write a graded 9:16 parallax clip. Returns (frames, depth source)."""
    bgr = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError(f"cannot read image {image_path}")
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    # Work on a frame 15% larger than the output so moves never show edges.
    pad = 1.15
    bw, bh = int(W * pad), int(H * pad)
    base = _cover(rgb, bw, bh)
    depth_full, source = load_depth(image_path, rgb)
    depth = _cover(depth_full[..., None].repeat(3, 2), bw, bh)[..., 0]

    p = PRESETS.get(motion, PRESETS["push"])
    frames = max(int(round(duration * FPS)), 1)
    ox, oy = (bw - W) / 2.0, (bh - H) / 2.0
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    d_out = depth[int(oy):int(oy) + H, int(ox):int(ox) + W]
    cx, cy = W / 2.0, H / 2.0

    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-vf", grade,
         "-frames:v", str(frames), "-an", "-c:v", "libx264",
         "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", out],
        stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for i in range(frames):
            t = i / max(frames - 1, 1)
            e = t * t * (3 - 2 * t)  # ease in and out
            zoom = 1.0 + p["zoom"] * strength * e * (0.35 + d_out)
            rel = (d_out - 0.5) * strength * (e - 0.5) * 2
            map_x = (xx - cx) / zoom + cx + ox - p["sx"] * rel
            map_y = (yy - cy) / zoom + cy + oy - p["sy"] * rel
            frame = cv2.remap(base, map_x, map_y, cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_REFLECT)
            proc.stdin.write(frame.tobytes())
        proc.stdin.close()
    except BrokenPipeError:
        pass
    if proc.wait() != 0:
        raise RuntimeError(proc.stderr.read().decode()[-500:])
    return frames, source
