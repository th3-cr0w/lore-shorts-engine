# Lore Shorts Engine

Turns a voice recording and a render spec into a finished 9:16 lore short:
timed shots, graded footage, word-by-word captions, a ducked sound bed and an
end card, plus a QA report.

## Cut one short

    pip install -r requirements.txt     # needs ffmpeg on the machine
    python -m engine.render --spec specs/W1-1.json --voice W1-1.m4a --out out/W1-1.mp4

Outputs `out/W1-1.mp4` and `out/W1-1.qa.json`.

## How timing works

1. Whisper hears the recording and gives each word a time. The script supplies
   the spelling, so lore names are always written correctly in captions.
2. If Whisper isn't available, or the recording strays from the script, the
   engine times lines by the pauses between them. Leave a short breath between
   lines when recording.

## Render spec

One JSON file per short (written by the remembrancer-weekly-scripts skill):
`id`, `series_tag`, `end_card`, and `lines`, each with `text`, `shot`
(STOCK, AI, SIL or TEXT), `query` (stock search terms), optional `on_screen`
(big text) and `asset` (path to the gathered clip or image). Lines without an
asset get a labelled placeholder.

## Parallax on artwork

Still images (Art bank works, AI landscapes) get a 2.5D camera move instead of
a flat zoom: near parts slide and grow more than far parts. Depth comes from
Depth Anything V2 Small on CPU and is cached as `<image>.depth.png`. If the
model can't load, a rough fallback keeps the render going. Moves cycle
through push, drift left, rise and drift right; set `"motion": "kenburns"` on
a line for a plain zoom.

Art bank lines use `"shot": "ART"` and `"art_id": "A007"`; the engine looks
for `assets/art/A007.jpg` (or .png/.webp), filled by the gather step.

Caption font: Anton (SIL Open Font License, see fonts/Anton-OFL.txt).

## Automatic pipeline (GitHub Actions)

Set-up for non-coders: **[SETUP.md](SETUP.md)**.

Google Drive holds one folder per short (`Lore Shorts/W1-1/`):

| File | Who puts it there |
|---|---|
| `spec.json` | the weekly script skill |
| `assets/` + `licences.csv` + `.done` | `pipeline/gather.py` (hourly) |
| `W1-1.m4a` (or .mp3/.wav) | you, from your phone |
| `W1-1.mp4`, `W1-1.qa.json` | `pipeline/watch_and_cut.py` (every 30 min) |

* `pipeline/gather.py` downloads open-licence artwork for ART lines (The Met
  and NGA via their open data, Cleveland CC0 only, Wikimedia Commons public
  domain / CC BY(-SA), NASA) and Pexels clips for STOCK/SIL lines. Anything
  whose licence is unclear (MoMA, Google Arts & Culture, Getty, non-free
  Wikipedia files) is skipped with a reason. It then writes `asset_file`
  into each spec line.
* `pipeline/watch_and_cut.py` cuts shorts whose voice file arrived, uploads
  the video, sets the Post log status to Recorded, and sends the video plus
  each platform's caption (`platform_copy` in the spec) to Telegram.
  **Nothing is ever posted automatically.**
* Workflows: `.github/workflows/gather.yml`, `cut.yml`, `keepalive.yml`.
* Keys come only from GitHub secrets (environment variables). None are stored
  in this repository.

Run the tests (no network needed; every web and Google call is faked):

    pip install -r requirements-dev.txt
    python -m pytest

## License

The code is under the MIT License (see `LICENSE`). The Anton caption font is
under the SIL Open Font License (`fonts/Anton-OFL.txt`). Downloaded artwork and
clips keep their own licences, which are listed per short in `licences.csv`.
