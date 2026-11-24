"""Pexels result picking: portrait first, HD next, long enough next."""
from pipeline import pexels


def video(vid, w, h, duration, files):
    return {"id": vid, "width": w, "height": h, "duration": duration,
            "url": f"https://www.pexels.com/video/{vid}/",
            "user": {"name": "Ann", "url": "https://www.pexels.com/@ann"},
            "video_files": [{"id": i, "file_type": "video/mp4", "width": fw,
                             "height": fh, "link": f"https://v/{vid}_{fw}.mp4"}
                            for i, (fw, fh) in enumerate(files)]}


LANDSCAPE_HD = video(1, 1920, 1080, 30, [(1920, 1080), (3840, 2160)])
PORTRAIT_SD = video(2, 540, 960, 30, [(540, 960)])
PORTRAIT_HD = video(3, 1080, 1920, 30, [(720, 1280), (1080, 1920), (2160, 3840)])
PORTRAIT_HD_SHORT = video(4, 1080, 1920, 3, [(1080, 1920)])


def test_pick_file_takes_smallest_hd_file():
    assert pexels.pick_file(PORTRAIT_HD)["width"] == 1080


def test_pick_file_falls_back_to_biggest():
    assert pexels.pick_file(PORTRAIT_SD)["width"] == 540


def test_portrait_beats_landscape():
    v, _ = pexels.choose([LANDSCAPE_HD, PORTRAIT_HD], target_s=5)
    assert v["id"] == 3


def test_hd_beats_sd():
    v, _ = pexels.choose([PORTRAIT_SD, PORTRAIT_HD], target_s=5)
    assert v["id"] == 3


def test_long_enough_beats_short():
    v, _ = pexels.choose([PORTRAIT_HD_SHORT, PORTRAIT_HD], target_s=6)
    assert v["id"] == 3


def test_ties_keep_relevance_order():
    v, _ = pexels.choose([PORTRAIT_HD_SHORT, PORTRAIT_HD], target_s=2)
    assert v["id"] == 4


def test_used_clips_are_not_repeated():
    v, _ = pexels.choose([PORTRAIT_HD, PORTRAIT_SD], target_s=5, used_ids={3})
    assert v["id"] == 2


def test_nothing_usable():
    assert pexels.choose([], 5) == (None, None)


def test_estimate_seconds():
    assert pexels.estimate_seconds({"text": "one two three four five six"}) == 2.7
    assert pexels.estimate_seconds({"text": "x", "duration_s": 4}) == 4.0


def test_find_clip_searches_portrait_with_key_in_header(web):
    def answer(params):
        return {"videos": [PORTRAIT_HD] if params["query"] == "burning city night"
                else []}
    web.json[pexels.SEARCH_URL] = answer
    line = {"text": "The Emperor's favourite son set the galaxy on fire.",
            "query": ["burning city night", "fire embers dark"]}
    v, f = pexels.find_clip(line, "KEY")
    assert v["id"] == 3 and f["width"] == 1080
    url, params, headers = web.calls[0]
    assert params["orientation"] == "portrait"
    assert headers == {"Authorization": "KEY"}
    assert len(web.calls) == 1  # first query already gave a portrait HD clip


def test_find_clip_tries_any_orientation_when_no_portrait(web):
    def answer(params):
        return {"videos": [LANDSCAPE_HD] if "orientation" not in params else []}
    web.json[pexels.SEARCH_URL] = answer
    v, _ = pexels.find_clip({"text": "x", "query": ["space nebula"]}, "KEY")
    assert v["id"] == 1
