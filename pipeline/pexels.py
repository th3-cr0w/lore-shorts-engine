"""Find a stock clip on Pexels for a STOCK or SIL line.

Preference, in order: portrait (9:16-ish) clips, a file at least 1080 px on
its short side, a clip at least as long as the spoken line, then Pexels'
own relevance order. Pexels licence: free to use, credit appreciated.
"""
import os

from . import http

SEARCH_URL = "https://api.pexels.com/videos/search"
WORDS_PER_SECOND = 2.6  # typical narration pace, to guess a line's length


def estimate_seconds(line):
    """How long the line will be on screen (uses a known value if given)."""
    for key in ("duration_s", "seconds", "length_s"):
        if line.get(key):
            return float(line[key])
    words = len((line.get("text") or "").split())
    return round(words / WORDS_PER_SECOND + 0.4, 1) if words else None


def search(query, api_key, orientation="portrait", per_page=15):
    params = {"query": query, "per_page": per_page, "size": "medium"}
    if orientation:
        params["orientation"] = orientation
    resp = http.get_json(SEARCH_URL, params=params,
                         headers={"Authorization": api_key})
    return resp.get("videos", [])


def pick_file(video, min_short_side=1080, max_short_side=2160):
    """Best MP4 file of a video: the smallest one that is HD enough
    (saves download time), else the biggest one available."""
    files = [f for f in video.get("video_files", [])
             if f.get("file_type", "video/mp4") == "video/mp4"
             and f.get("link") and f.get("width") and f.get("height")]
    if not files:
        return None

    def short_side(f):
        return min(f["width"], f["height"])

    good = [f for f in files if min_short_side <= short_side(f) <= max_short_side]
    if good:
        return min(good, key=short_side)
    return max(files, key=short_side)


def score(video, file, target_s):
    """Higher is better. Tuple compares left to right."""
    portrait = video.get("height", 0) > video.get("width", 0)
    hd = min(file["width"], file["height"]) >= 1080
    long_enough = target_s is None or video.get("duration", 0) >= target_s
    return (portrait, hd, long_enough)


def choose(videos, target_s=None, used_ids=()):
    """Pick (video, file) from search results, or (None, None)."""
    best, best_score = (None, None), None
    for video in videos:  # results arrive in relevance order
        if video.get("id") in used_ids:
            continue
        file = pick_file(video)
        if not file:
            continue
        s = score(video, file, target_s)
        if best_score is None or s > best_score:  # ties keep the earlier one
            best, best_score = (video, file), s
    return best


def find_clip(line, api_key, used_ids=()):
    """Search each of the line's query terms; return (video, file) or
    (None, None). Tries portrait first, then any orientation."""
    queries = [q for q in (line.get("query") or []) if q.strip()]
    if not queries and line.get("on_screen"):
        queries = [line["on_screen"]]
    target = estimate_seconds(line)
    pool = []
    for q in queries[:3]:
        pool += search(q, api_key, orientation="portrait")
        video, file = choose(pool, target, used_ids)
        if video and score(video, file, target)[:2] == (True, True):
            return video, file
    if not any(v.get("height", 0) > v.get("width", 0) for v in pool) and queries:
        pool += search(queries[0], api_key, orientation=None)
    return choose(pool, target, used_ids)


def api_key():
    return os.environ.get("PEXELS_API_KEY", "").strip()
