"""Assemble the frames from demo/gif/capture.cjs into the README GIF, with short crossfades.

    python demo/gif/build_gif.py <frames-dir> <output.gif> [--width 960]

Needs Pillow (already installed with matplotlib from requirements.txt).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

FADE_STEPS = 4
FADE_MS = 60


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("frames_dir", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--width", type=int, default=960)
    args = parser.parse_args()

    manifest = json.loads((args.frames_dir / "frames.json").read_text(encoding="utf-8"))
    stills: list[tuple[Image.Image, int]] = []
    for entry in manifest:
        image = Image.open(args.frames_dir / entry["file"]).convert("RGB")
        height = round(image.height * args.width / image.width)
        stills.append((image.resize((args.width, height), Image.LANCZOS), int(entry["seconds"] * 1000)))

    frames: list[Image.Image] = []
    durations: list[int] = []
    for index, (image, hold_ms) in enumerate(stills):
        frames.append(image)
        durations.append(hold_ms)
        if index + 1 < len(stills):
            following = stills[index + 1][0]
            for step in range(1, FADE_STEPS + 1):
                frames.append(Image.blend(image, following, step / (FADE_STEPS + 1)))
                durations.append(FADE_MS)

    # One shared adaptive palette keeps UI colors stable across frames (no per-frame flicker).
    palette_source = Image.new("RGB", (args.width, sum(image.height for image, _ in stills)))
    offset = 0
    for image, _ in stills:
        palette_source.paste(image, (0, offset))
        offset += image.height
    palette = palette_source.quantize(colors=255, method=Image.Quantize.MEDIANCUT)
    quantized = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in frames]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    quantized[0].save(
        args.output,
        save_all=True,
        append_images=quantized[1:],
        duration=durations,
        loop=0,
        optimize=True,
        disposal=1,
    )
    total = sum(durations) / 1000
    size_mb = args.output.stat().st_size / 1_000_000
    print(f"wrote {args.output} ({len(frames)} frames, {total:.1f}s, {size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
