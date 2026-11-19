#!/usr/bin/env python3
"""Assemble and verify the standalone 25-second H.264 animation.

    python src/encode.py --frames build/frames/frame_%04d.png \
      --audio build/foley.wav --output film/Rolling-Ball.mp4

Frame completeness and the encoded streams are checked; no website is created.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import wave


def run(command):
    subprocess.run(command, check=True)


def verify_video(path, fps=24, duration=25, expected_frames=None):
    expected_frames = expected_frames or int(round(fps * duration))
    command = ["ffprobe", "-v", "error", "-count_frames", "-show_streams", "-show_format", "-of", "json", str(path)]
    probe = json.loads(subprocess.check_output(command))
    videos = [s for s in probe["streams"] if s["codec_type"] == "video"]
    audios = [s for s in probe["streams"] if s["codec_type"] == "audio"]
    if len(videos) != 1 or len(audios) != 1:
        raise AssertionError("Expected one video stream and one audio stream")
    video, audio = videos[0], audios[0]
    numerator, denominator = map(int, video["avg_frame_rate"].split("/"))
    assert numerator / denominator == fps, video["avg_frame_rate"]
    assert int(video["nb_read_frames"]) == expected_frames, video["nb_read_frames"]
    assert abs(float(video["duration"]) - duration) <= 1 / fps / 10
    assert abs(float(audio["duration"]) - duration) <= .05
    assert video["codec_name"] == "h264"
    assert video["pix_fmt"] == "yuv420p"
    assert audio["codec_name"] == "aac"
    assert audio["channels"] == 2
    assert int(audio["sample_rate"]) == 48000
    # A complete decode catches corrupt images/packets beyond header metadata.
    run(["ffmpeg", "-hide_banner", "-v", "error", "-i", str(path), "-f", "null", "-"])
    return {
        "file": str(path),
        "duration_seconds": float(video["duration"]),
        "video_frames": int(video["nb_read_frames"]),
        "fps": fps,
        "width": video["width"],
        "height": video["height"],
        "video_codec": video["codec_name"],
        "pixel_format": video["pix_fmt"],
        "audio_codec": audio["codec_name"],
        "audio_channels": audio["channels"],
        "audio_sample_rate": int(audio["sample_rate"]),
        "full_decode": "passed",
        "file_bytes": Path(path).stat().st_size,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", required=True, help="printf image sequence, e.g. build/frames/frame_%%04d.png")
    parser.add_argument("--audio", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--duration", type=float, default=25)
    parser.add_argument("--crf", type=int, default=17)
    parser.add_argument("--preset", default="slow")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    for binary in ("ffmpeg", "ffprobe"):
        if not shutil.which(binary):
            raise SystemExit(f"{binary} is required")
    total_frames = round(args.duration * args.fps)
    if not args.verify_only:
        missing = []
        for index in range(args.start, args.start + total_frames):
            path = Path(args.frames % index)
            if not path.is_file() or path.stat().st_size == 0:
                missing.append(str(path))
        if missing:
            raise SystemExit(f"Missing {len(missing)} rendered frames. First missing: {missing[:5]}")
        with wave.open(str(args.audio), "rb") as sound:
            if sound.getnchannels() != 2 or sound.getframerate() != 48000:
                raise SystemExit("Expected 48 kHz stereo WAV")
            if abs(sound.getnframes() / sound.getframerate() - args.duration) > 1 / 48000:
                raise SystemExit("WAV duration does not match requested film duration")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        run([
            "ffmpeg", "-hide_banner", "-loglevel", "warning", "-y",
            "-framerate", str(args.fps), "-start_number", str(args.start), "-i", args.frames,
            "-i", str(args.audio), "-map", "0:v:0", "-map", "1:a:0",
            "-frames:v", str(total_frames), "-t", str(args.duration),
            "-c:v", "libx264", "-preset", args.preset, "-crf", str(args.crf),
            "-pix_fmt", "yuv420p", "-profile:v", "high", "-r", str(args.fps),
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", "-metadata", "title=Rolling Ball — A Mechanical Chain Reaction",
            "-metadata", "comment=Rendered 3D film. Mechanical Foley synchronised to causal simulation events.",
            str(args.output),
        ])
    report = verify_video(args.output, args.fps, args.duration, total_frames)
    args.output.with_suffix(".verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
