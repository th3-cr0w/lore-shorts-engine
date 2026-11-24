"""Make two stand-in artworks for testing parallax without downloads.

TEST1: layered gothic skyline with an exact depth map (TEST1.depth.png),
       to judge the camera moves.
TEST2: same kind of image with no depth map, to exercise the fallback.
"""
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

OUT = os.path.join(os.path.dirname(__file__), "..", "assets", "art")
os.makedirs(OUT, exist_ok=True)
W, H = 1600, 2600
rng = np.random.default_rng(7)


def spire(draw, dd, x, base, width, height, color, depth):
    top = base - height
    pts = [(x - width / 2, base), (x - width / 2, top + height * 0.35),
           (x, top), (x + width / 2, top + height * 0.35), (x + width / 2, base)]
    draw.polygon(pts, fill=color)
    dd.polygon(pts, fill=depth)
    for k in range(3):  # windows
        wy = base - height * (0.15 + 0.18 * k)
        draw.rectangle([x - width * 0.08, wy - 40, x + width * 0.08, wy],
                       fill=(200, 120, 50) if k == 1 else color)


def make(name, with_depth, seed):
    rng = np.random.default_rng(seed)
    sky = np.zeros((H, W, 3), np.uint8)
    for y in range(H):
        f = y / H
        sky[y] = (int(30 + 60 * f), int(12 + 20 * f), int(10 + 10 * f))
    img = Image.fromarray(sky)
    depth = Image.new("L", (W, H), 0)
    d, dd = ImageDraw.Draw(img), ImageDraw.Draw(depth)
    d.ellipse([W * 0.55, H * 0.12, W * 0.85, H * 0.12 + W * 0.3],
              fill=(150, 60, 30))  # dying sun
    layers = [  # (base y, colour, depth, count, scale)
        (H * 0.62, (70, 40, 38), 40, 9, 0.6),
        (H * 0.74, (42, 24, 24), 120, 6, 0.9),
        (H * 0.88, (20, 12, 12), 200, 4, 1.3),
    ]
    for base, color, dv, count, scale in layers:
        d.rectangle([0, base, W, H], fill=color)
        dd.rectangle([0, base, W, H], fill=dv)
        for i in range(count):
            x = (i + rng.uniform(0.1, 0.9)) * W / count
            spire(d, dd, x, base + 2, 140 * scale, rng.uniform(500, 900) * scale,
                  color, dv)
    # foreground ruined arch
    d.rectangle([0, H * 0.93, W, H], fill=(8, 5, 5))
    dd.rectangle([0, H * 0.93, W, H], fill=255)
    d.rectangle([60, H * 0.45, 220, H], fill=(8, 5, 5))
    dd.rectangle([60, H * 0.45, 220, H], fill=255)
    img = img.filter(ImageFilter.GaussianBlur(1.2))
    img.save(os.path.join(OUT, f"{name}.png"))
    if with_depth:
        depth.save(os.path.join(OUT, f"{name}.depth.png"))


make("TEST1", True, 7)
make("TEST2", False, 11)
print("ok")
