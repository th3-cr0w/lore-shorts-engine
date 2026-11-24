"""Line up the voice recording with the script.

Speech recognition gives words with times. The script gives the exact words
(with correct lore spelling). We match the two so every script word gets a
start and end time, then derive each script line's start and end.
"""
import difflib
import json
import re
import subprocess


WORD_RE = re.compile(r"[A-Za-z0-9']+")


def norm(word):
    return re.sub(r"[^a-z0-9]", "", word.lower())


def audio_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", path], capture_output=True, text=True, check=True)
    return float(json.loads(out.stdout)["format"]["duration"])


def to_wav16k(src, dst):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src, "-ac", "1",
                    "-ar", "16000", "-sample_fmt", "s16", dst], check=True)
    return dst


def recognise_whisper(wav_path):
    """Production backend (GitHub Actions): faster-whisper with word times."""
    from faster_whisper import WhisperModel
    model = WhisperModel("small.en", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(wav_path, word_timestamps=True,
                                   vad_filter=True)
    words = []
    for seg in segments:
        for w in seg.words or []:
            words.append((w.word.strip(), w.start, w.end))
    return words


def silences(wav_path, noise_db=-35, min_len=0.2):
    """Pauses in the recording, as (start, end) pairs."""
    out = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", wav_path, "-af",
         f"silencedetect=noise={noise_db}dB:d={min_len}", "-f", "null", "-"],
        capture_output=True, text=True).stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", out)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", out)]
    return list(zip(starts, ends + [None] * (len(starts) - len(ends))))


def align_by_pauses(script_lines, wav_path, total):
    """Fallback that needs no speech recognition: the longest pauses mark the
    line changes, and words inside a line are spread by their length.
    Works best when lines are read with a short breath between them."""
    gaps = [(s, e if e is not None else total) for s, e in silences(wav_path)]
    speech_start = gaps[0][1] if gaps and gaps[0][0] < 0.05 else 0.0
    speech_end = gaps[-1][0] if gaps and gaps[-1][1] >= total - 0.05 else total
    inner = [g for g in gaps if g[0] > speech_start and g[1] < speech_end]
    needed = len(script_lines) - 1
    cuts = sorted(sorted(inner, key=lambda g: g[1] - g[0], reverse=True)[:needed])
    if len(cuts) < needed:  # too few pauses: share time by line length
        weights = [len(l) for l in script_lines]
        span, acc, bounds = speech_end - speech_start, speech_start, []
        for w in weights:
            nxt = acc + span * w / sum(weights)
            bounds.append((acc, nxt))
            acc = nxt
    else:
        edges = [speech_start] + [x for g in cuts for x in g] + [speech_end]
        bounds = [(edges[i], edges[i + 1]) for i in range(0, len(edges), 2)]
    heard = []
    for (s, e), line in zip(bounds, script_lines):
        words = WORD_RE.findall(line)
        weights = [len(w) + 2 for w in words]
        acc = s
        for w, wt in zip(words, weights):
            d = (e - s) * wt / sum(weights)
            heard.append((w, acc, acc + d))
            acc += d
    return heard


def _match_ratio(script_words, heard):
    a = [norm(w["text"]) for w in script_words]
    b = [norm(h[0]) for h in heard]
    m = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return sum(bl.size for bl in m.get_matching_blocks()) / max(len(a), 1)


def align(script_lines, voice_path, workdir, backend="auto"):
    """Return per-word and per-line timings for the script.

    script_lines: list of line texts.
    Returns dict with words [{text, start, end, line}], lines [{start, end}],
    duration, backend, match_ratio.
    """
    wav = to_wav16k(voice_path, f"{workdir}/voice16k.wav")
    total = audio_duration(wav)

    heard, used = [], "pauses"
    if backend in ("auto", "whisper"):
        try:
            heard, used = recognise_whisper(wav), "whisper"
        except Exception as exc:  # model missing or not installed
            if backend == "whisper":
                raise
            print(f"[align] whisper unavailable ({type(exc).__name__}), "
                  "timing by pauses")

    script_words = []
    for li, line in enumerate(script_lines):
        for w in WORD_RE.findall(line):
            script_words.append({"text": w, "line": li})

    if used == "whisper":
        ratio = _match_ratio(script_words, heard)
        if ratio < 0.6:  # recording strayed from the script: be safe
            print(f"[align] whisper matched only {ratio:.0%}, timing by pauses")
            used = "pauses"
    if used == "pauses":
        heard = align_by_pauses(script_lines, wav, total)

    a = [norm(w["text"]) for w in script_words]
    b = [norm(h[0]) for h in heard]
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    times = [None] * len(script_words)
    matched = 0
    for block in matcher.get_matching_blocks():
        for k in range(block.size):
            h = heard[block.b + k]
            times[block.a + k] = (h[1], h[2])
            matched += 1

    # Words the recogniser missed (often lore names) get times spread
    # evenly between the nearest matched neighbours.
    known = [i for i, t in enumerate(times) if t]
    speech_start = heard[0][1] if heard else 0.0
    speech_end = heard[-1][2] if heard else total
    if not known:
        step = (speech_end - speech_start) / max(len(times), 1)
        times = [(speech_start + i * step, speech_start + (i + 1) * step)
                 for i in range(len(times))]
    else:
        i = 0
        while i < len(times):
            if times[i]:
                i += 1
                continue
            j = i
            while j < len(times) and not times[j]:
                j += 1
            left = times[i - 1][1] if i > 0 else speech_start
            right = times[j][0] if j < len(times) else speech_end
            n = j - i
            step = max(right - left, 0.12 * n) / n
            for k in range(n):
                s = left + k * step
                times[i + k] = (s, s + step * 0.9)
            i = j

    words = []
    for w, (s, e) in zip(script_words, times):
        words.append({"text": w["text"], "line": w["line"],
                      "start": round(s, 3), "end": round(max(e, s + 0.08), 3)})

    # Line boundaries: a line starts where its first word starts and runs
    # until the next line starts, so shots cut on the spoken line change.
    firsts = {}
    for w in words:
        firsts.setdefault(w["line"], w["start"])
    lines = []
    for li in range(len(script_lines)):
        start = 0.0 if li == 0 else firsts.get(li, 0.0)
        end = firsts.get(li + 1, total)
        lines.append({"start": round(start, 3), "end": round(end, 3)})

    # With pause timing the words are placed from the script itself, so
    # there is no independent check that the recording matches the script.
    ratio = (round(matched / max(len(script_words), 1), 3)
             if used == "whisper" else None)
    return {"words": words, "lines": lines, "duration": total,
            "backend": used, "match_ratio": ratio}
