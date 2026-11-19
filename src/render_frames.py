"""Render an exact frame range from the committed Blender scene.

Example (official Blender 4.3.2, including Open Image Denoise):
  blender -b scene/Rolling-Ball.blend -t 4 --python src/render_frames.py -- \
    --start 1 --end 30 --output build/frames --samples 32 \
    --width 1920 --height 1080 --denoise

This script changes render settings only. All object movement and the continuous
camera move already live in the scene's baked animation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import time
from pathlib import Path

import bpy


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=32)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--denoise", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    args = parser.parse_args(argv)
    if not 1 <= args.start <= args.end <= 600:
        parser.error("The film consists of frames 1 through 600 inclusive")
    if args.samples < 1 or args.width < 1 or args.height < 1:
        parser.error("Samples and dimensions must be positive")
    return args


def inspect_png(path: Path, width: int, height: int):
    payload = path.read_bytes()
    if payload[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"Not a PNG frame: {path}")
    actual = struct.unpack(">II", payload[16:24])
    if actual != (width, height):
        raise ValueError(f"Incorrect frame dimensions: {path}: {actual}")
    return {"file": path.name, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def main():
    args = arguments()
    if not bpy.data.filepath:
        raise RuntimeError("Load scene/Rolling-Ball.blend before running this script")
    scene = bpy.context.scene
    if not scene.camera:
        raise RuntimeError("The scene has no film camera")
    if scene.frame_start != 1 or scene.frame_end != 600:
        raise RuntimeError("The baked scene must contain the full 600-frame film")
    if scene.render.fps != 24 or scene.render.fps_base != 1:
        raise RuntimeError("The baked film must run at 24 fps")
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = args.samples
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.adaptive_threshold = 0.025
    scene.cycles.adaptive_min_samples = min(8, args.samples)
    scene.cycles.use_denoising = args.denoise
    if args.denoise:
        scene.cycles.denoiser = "OPENIMAGEDENOISE"
        scene.cycles.denoising_input_passes = "RGB_ALBEDO_NORMAL"
        scene.cycles.denoising_prefilter = "ACCURATE"
        if hasattr(scene.cycles, "denoising_use_gpu"):
            scene.cycles.denoising_use_gpu = False
    scene.render.resolution_x = args.width
    scene.render.resolution_y = args.height
    scene.render.resolution_percentage = 100
    scene.render.use_persistent_data = True
    if hasattr(scene.render, "use_motion_blur"):
        scene.render.use_motion_blur = False
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.color_depth = "8"
    scene.render.image_settings.compression = 15
    scene.render.use_file_extension = True
    args.output.mkdir(parents=True, exist_ok=True)
    begun = time.perf_counter()
    frames = []
    for frame in range(args.start, args.end + 1):
        path = (args.output / f"frame_{frame:04d}.png").resolve()
        if not (args.skip_existing and path.is_file()):
            scene.frame_set(frame)
            scene.render.filepath = str(path)
            bpy.ops.render.render(write_still=True)
        frames.append(inspect_png(path, args.width, args.height))
        print(f"FILM_FRAME_COMPLETE {frame:04d} elapsed={time.perf_counter()-begun:.2f}s", flush=True)
    manifest = {
        "scene": Path(bpy.data.filepath).name,
        "blender_version": bpy.app.version_string,
        "first_frame": args.start,
        "last_frame": args.end,
        "frame_count": len(frames),
        "fps": 24,
        "width": args.width,
        "height": args.height,
        "max_samples": args.samples,
        "denoiser": "OPENIMAGEDENOISE" if args.denoise else None,
        "seconds": round(time.perf_counter() - begun, 3),
        "frames": frames,
    }
    path = args.output / f"chunk_{args.start:04d}-{args.end:04d}.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"FILM_CHUNK_COMPLETE {path}", flush=True)


if __name__ == "__main__":
    main()
