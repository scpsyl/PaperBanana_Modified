#!/usr/bin/env python3
"""
Standalone vtracer PNG→SVG converter.
Runs inside its own venv, called via subprocess from the main app.

Usage:
    python convert.py <input_png> <output_svg> [--preset <preset>] [options]
    python convert.py --base64 <output_svg> [--preset <preset>] [options]
        (reads base64-encoded PNG from stdin)

Presets:
    diagram  - optimized for scientific diagrams (default): sharp edges, high fidelity
    photo    - optimized for photographs: smoother curves
    poster   - optimized for poster-style graphics
"""

import argparse
import base64
import sys
import tempfile
from pathlib import Path

import vtracer
from PIL import Image


PRESETS = {
    "diagram": {
        "colormode": "color",
        "hierarchical": "stacked",
        "mode": "spline",
        "filter_speckle": 4,
        "color_precision": 8,
        "layer_difference": 16,
        "corner_threshold": 60,
        "length_threshold": 4.0,
        "max_iterations": 10,
        "splice_threshold": 45,
        "path_precision": 3,
    },
    "photo": {
        "colormode": "color",
        "hierarchical": "stacked",
        "mode": "spline",
        "filter_speckle": 10,
        "color_precision": 6,
        "layer_difference": 32,
        "corner_threshold": 60,
        "length_threshold": 4.0,
        "max_iterations": 10,
        "splice_threshold": 45,
        "path_precision": 2,
    },
    "poster": {
        "colormode": "color",
        "hierarchical": "stacked",
        "mode": "polygon",
        "filter_speckle": 8,
        "color_precision": 5,
        "layer_difference": 48,
        "corner_threshold": 60,
        "length_threshold": 4.0,
        "max_iterations": 10,
        "splice_threshold": 45,
        "path_precision": 2,
    },
}


def convert_png_to_svg(input_path: str, output_path: str, preset: str = "diagram", **overrides) -> str:
    """Convert a PNG image to SVG using vtracer."""
    params = PRESETS.get(preset, PRESETS["diagram"]).copy()
    params.update({k: v for k, v in overrides.items() if v is not None})

    img = Image.open(input_path)
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        img.save(tmp.name, format="PNG")
        tmp_path = tmp.name

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    vtracer.convert_image_to_svg_py(
        image_path=tmp_path,
        out_path=output_path,
        colormode=params["colormode"],
        hierarchical=params["hierarchical"],
        mode=params["mode"],
        filter_speckle=params["filter_speckle"],
        color_precision=params["color_precision"],
        layer_difference=params["layer_difference"],
        corner_threshold=params["corner_threshold"],
        length_threshold=params["length_threshold"],
        max_iterations=params["max_iterations"],
        splice_threshold=params["splice_threshold"],
        path_precision=params["path_precision"],
    )

    Path(tmp_path).unlink(missing_ok=True)

    return output_path


def main():
    parser = argparse.ArgumentParser(description="PNG to SVG converter via vtracer")
    parser.add_argument("input", nargs="?", help="Input PNG file path")
    parser.add_argument("output", help="Output SVG file path")
    parser.add_argument("--base64", action="store_true",
                        help="Read base64-encoded PNG from stdin instead of file")
    parser.add_argument("--preset", default="diagram",
                        choices=list(PRESETS.keys()),
                        help="Conversion preset (default: diagram)")
    parser.add_argument("--filter-speckle", type=int, default=None)
    parser.add_argument("--color-precision", type=int, default=None)
    parser.add_argument("--corner-threshold", type=int, default=None)
    args = parser.parse_args()

    if args.base64:
        b64_data = sys.stdin.read().strip()
        raw_bytes = base64.b64decode(b64_data)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(raw_bytes)
            input_path = tmp.name
    elif args.input:
        input_path = args.input
    else:
        parser.error("Either provide an input file or use --base64")

    overrides = {}
    if args.filter_speckle is not None:
        overrides["filter_speckle"] = args.filter_speckle
    if args.color_precision is not None:
        overrides["color_precision"] = args.color_precision
    if args.corner_threshold is not None:
        overrides["corner_threshold"] = args.corner_threshold

    result = convert_png_to_svg(input_path, args.output, preset=args.preset, **overrides)
    print(f"OK:{result}")

    if args.base64 and input_path:
        Path(input_path).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
