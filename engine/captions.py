"""Write the captions file (ASS): word-by-word captions, series tag,
big on-screen text for TEXT shots, and the end card text."""
import re

WORD_RE = re.compile(r"[A-Za-z0-9']+")
GOLD = "&H004AB0E8&"   # ASS colours are &HAABBGGRR
WHITE = "&H00FFFFFF&"

HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},96,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,0,0,0,0,100,100,1,0,1,7,2,2,90,90,560,1
Style: Tag,{font},46,&H004AB0E8,&H004AB0E8,&H00000000,&H00000000,0,0,0,0,100,100,4,0,1,3,0,8,80,80,190,1
Style: Big,{font},170,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,2,0,1,9,0,5,60,60,0,1
Style: End,{font},104,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,2,0,1,6,0,5,80,80,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def ts(seconds):
    seconds = max(seconds, 0)
    h = int(seconds // 3600)
    m = int(seconds % 3600 // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _punct_flags(line_text):
    """For each word in the line, True if a pause follows it in the text."""
    flags = []
    for token in line_text.split():
        words = WORD_RE.findall(token)
        for k, _ in enumerate(words):
            last = k == len(words) - 1
            flags.append(last and bool(re.search(r"[.,!?;:—-]$", token)))
    return flags


def chunk_words(words, script_lines, max_words=3):
    """Group aligned words into caption chunks of up to 3 words, breaking at
    punctuation and line changes."""
    flags = []
    for line in script_lines:
        flags.extend(_punct_flags(line))
    chunks, current = [], []
    for i, w in enumerate(words):
        if current and (w["line"] != current[-1]["line"]
                        or len(current) >= max_words):
            chunks.append(current)
            current = []
        current.append(w)
        if i < len(flags) and flags[i]:
            chunks.append(current)
            current = []
    if current:
        chunks.append(current)
    return chunks


def build(alignment, spec, script_lines, total, out_path, font_name):
    words = alignment["words"]
    chunks = chunk_words(words, script_lines)
    events = []

    # Word-by-word captions: the chunk stays up, the spoken word turns gold.
    for ci, chunk in enumerate(chunks):
        next_start = (chunks[ci + 1][0]["start"] if ci + 1 < len(chunks)
                      else chunk[-1]["end"] + 0.4)
        chunk_end = min(chunk[-1]["end"] + 0.35, next_start)
        for k, w in enumerate(chunk):
            start = w["start"]
            end = chunk[k + 1]["start"] if k + 1 < len(chunk) else chunk_end
            if end <= start:
                end = start + 0.05
            parts = []
            for j, other in enumerate(chunk):
                text = other["text"].upper()
                if j == k:
                    parts.append(f"{{\\c{GOLD}\\fscx108\\fscy108}}{text}"
                                 f"{{\\c{WHITE}\\fscx100\\fscy100}}")
                else:
                    parts.append(text)
            pop = "{\\fscx88\\fscy88\\t(0,90,\\fscx100\\fscy100)}" if k == 0 else ""
            events.append(f"Dialogue: 1,{ts(start)},{ts(end)},Cap,,0,0,0,,"
                          f"{pop}{' '.join(parts)}")

    voice_end = alignment["duration"]

    # Series tag across the whole short.
    tag = spec.get("series_tag")
    if tag:
        events.append(f"Dialogue: 0,{ts(0)},{ts(voice_end)},Tag,,0,0,0,,"
                      f"{tag.upper()}")

    # Big on-screen words for TEXT shots.
    for li, line in enumerate(spec["lines"]):
        if line.get("on_screen"):
            seg = alignment["lines"][li]
            events.append(
                f"Dialogue: 0,{ts(seg['start'])},{ts(seg['end'])},Big,,0,0,0,,"
                f"{{\\fad(150,150)\\fscx92\\fscy92\\t(0,400,\\fscx100\\fscy100)}}"
                f"{line['on_screen'].upper()}")

    # End card text over the tail after the voice.
    end_text = spec.get("end_card")
    if end_text:
        events.append(f"Dialogue: 0,{ts(voice_end)},{ts(total)},End,,0,0,0,,"
                      f"{{\\fad(200,0)}}{end_text.upper()}")

    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(HEADER.format(font=font_name))
        fh.write("\n".join(events) + "\n")
    return len(chunks)
