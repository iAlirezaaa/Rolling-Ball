#!/usr/bin/env python3
"""Deterministic, event-synchronised Foley for the Rolling Ball film.

No recorded assets, music, speech, network access, or licensed samples are used.
All timings come from the simulator's event log. Output is stereo PCM at 48 kHz.

    python src/audio.py --simulation build/simulation.json --output build/foley.wav
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import wave

import numpy as np
from scipy.signal import butter, sosfilt


SAMPLE_RATE = 48_000
DURATION = 25.0
SEED = 42_107


def _event_list(data):
    """Accept a named event mapping or a list, preserving film-time semantics."""
    raw = data.get("events", data.get("event_log", []))
    if isinstance(raw, dict):
        result = []
        for name, value in raw.items():
            if isinstance(value, dict):
                result.append({"name": name, **value})
            elif value is not None:
                result.append({"name": name, "time": float(value)})
        return result
    return list(raw)


def _name(event):
    return str(event.get("name", event.get("type", event.get("event", "")))).lower()


def _time(event):
    for key in ("film_time", "time", "t", "time_seconds", "film_seconds"):
        if key in event:
            return float(event[key])
    if "frame" in event:
        return (int(event["frame"]) - 1) / 24.0
    raise ValueError(f"Event has no usable film time: {event!r}")


def _first(events, names, default=None):
    matches = [e for e in events if any(n in _name(e) for n in names)]
    return min((_time(e) for e in matches), default=default)


def _band_noise(rng, duration, low=180, high=7000):
    count = max(1, int(duration * SAMPLE_RATE))
    noise = rng.standard_normal(count)
    sos = butter(2, (low, high), btype="bandpass", fs=SAMPLE_RATE, output="sos")
    return sosfilt(sos, noise)


def _fade(sound, attack=0.003, release=0.02):
    sound = np.asarray(sound, dtype=np.float64).copy()
    a = min(len(sound), int(attack * SAMPLE_RATE))
    r = min(len(sound), int(release * SAMPLE_RATE))
    if a:
        sound[:a] *= np.sin(np.linspace(0, np.pi / 2, a)) ** 2
    if r:
        sound[-r:] *= np.cos(np.linspace(0, np.pi / 2, r)) ** 2
    return sound


class Mix:
    def __init__(self, duration=DURATION):
        self.duration = duration
        self.buffer = np.zeros((int(round(SAMPLE_RATE * duration)), 2), dtype=np.float64)
        self.cues = []

    def add(self, mono, time, level=1.0, pan=0.0, label=None):
        start = int(round(time * SAMPLE_RATE))
        if start >= len(self.buffer):
            return
        mono = np.asarray(mono, dtype=np.float64)
        if start < 0:
            mono = mono[-start:]
            start = 0
        count = min(len(mono), len(self.buffer) - start)
        if count <= 0:
            return
        p = np.clip(pan, -1.0, 1.0)
        gains = np.array([np.cos((p + 1) * np.pi / 4), np.sin((p + 1) * np.pi / 4)])
        self.buffer[start:start + count] += mono[:count, None] * gains * level
        if label:
            self.cues.append({"cue": label, "time": round(time, 6), "duration": round(count / SAMPLE_RATE, 6)})

    def finish(self, path):
        # Sparse early reflections preserve transients and do not turn the workshop
        # into an exaggerated cathedral. Reflections are lower on the opposite side.
        dry = self.buffer.copy()
        for delay, gain, swap in ((.037, .11, False), (.083, .075, True), (.131, .045, False), (.211, .025, True)):
            shift = int(delay * SAMPLE_RATE)
            reflected = dry[:-shift, ::-1] if swap else dry[:-shift]
            self.buffer[shift:] += reflected * gain
        self.buffer -= self.buffer.mean(axis=0)
        self.buffer[-int(.12 * SAMPLE_RATE):] *= np.linspace(1, 0, int(.12 * SAMPLE_RATE))[:, None]
        peak_before = float(np.max(np.abs(self.buffer)))
        target_peak = 10 ** (-1.5 / 20)
        gain = min(1.0, target_peak / max(peak_before, 1e-12))
        self.buffer *= gain
        peak = float(np.max(np.abs(self.buffer)))
        if peak >= 1:
            raise AssertionError("Audio clipping detected")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        pcm = np.round(self.buffer * 32767).astype("<i2")
        with wave.open(str(path), "wb") as out:
            out.setnchannels(2)
            out.setsampwidth(2)
            out.setframerate(SAMPLE_RATE)
            out.writeframes(pcm.tobytes())
        report = {
            "duration_seconds": len(self.buffer) / SAMPLE_RATE,
            "sample_rate": SAMPLE_RATE,
            "channels": 2,
            "peak_dbfs": 20 * math.log10(max(peak, 1e-12)),
            "rms_dbfs": 20 * math.log10(max(float(np.sqrt(np.mean(self.buffer ** 2))), 1e-12)),
            "clipped_samples": int(np.sum(np.abs(self.buffer) >= 1)),
            "seed": SEED,
            "source": "Procedural Foley generated from simulation events; no music or external recordings",
            "cues": self.cues,
        }
        path.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n")
        return report


def _wood_clack(rng, index):
    t = np.arange(int(.25 * SAMPLE_RATE)) / SAMPLE_RATE
    noise = _band_noise(rng, len(t) / SAMPLE_RATE, 350, 8500)
    # Walnut's dull body with a short, hard brass-edge transient.
    body = (np.sin(2 * np.pi * (580 + index * 23) * t) * np.exp(-t / .038)
            + .47 * np.sin(2 * np.pi * (1120 + index * 31) * t) * np.exp(-t / .019)
            + .24 * np.sin(2 * np.pi * 2190 * t) * np.exp(-t / .011))
    sound = .42 * noise * np.exp(-t / .007) + .36 * body
    return _fade(sound, .0003, .015)


def _metal_click(rng, duration=.16):
    t = np.arange(int(duration * SAMPLE_RATE)) / SAMPLE_RATE
    sound = .42 * _band_noise(rng, duration, 1100, 11000) * np.exp(-t / .008)
    sound += .22 * np.sin(2 * np.pi * 2380 * t) * np.exp(-t / .025)
    sound += .09 * np.sin(2 * np.pi * 4790 * t) * np.exp(-t / .018)
    return _fade(sound, .00025, .012)


def _bell(rng, duration=7.0):
    t = np.arange(int(duration * SAMPLE_RATE)) / SAMPLE_RATE
    sound = np.zeros_like(t)
    # An intentionally inharmonic bronze-bell modal spectrum. Each overtone has its
    # own decay, with slight beating from neighboring modes instead of a pure sine.
    for hz, amp, decay in ((827, .46, 2.9), (1337, .27, 2.25), (1841, .19, 1.65), (2573, .13, 1.2), (3611, .075, .82), (4763, .04, .55)):
        mode = np.sin(2 * np.pi * hz * t) + .17 * np.sin(2 * np.pi * (hz * 1.0027) * t)
        sound += amp * mode * np.exp(-t / decay)
    sound *= 1 - np.exp(-t / .0011)
    sound += .12 * _band_noise(rng, duration, 700, 9000) * np.exp(-t / .007)
    return _fade(sound, .0003, .15)


def synthesize(data, output, duration=DURATION):
    events = _event_list(data)
    if not events:
        raise ValueError("Simulation contains no mechanical events; refusing unsynchronised audio")
    rng = np.random.default_rng(SEED)
    mix = Mix(duration)

    first_hit = _first(events, ("ball_domino", "marble_impact", "domino_1", "domino1", "first_domino", "marble_contact"))
    domino_events = [e for e in events if "domino" in _name(e) and not any(k in _name(e) for k in ("latch", "sear", "release", "trip", "settled", "complete"))]
    if first_hit is None and domino_events:
        first_hit = min(_time(e) for e in domino_events)
    if first_hit is None:
        raise ValueError("Missing marble/first-domino contact event")

    # Marble on polished rails: textured contact, with the modal brightness growing
    # with speed. It stops exactly at first impact, avoiding a looping stock sound.
    if first_hit > 0:
        count = int(first_hit * SAMPLE_RATE)
        t = np.arange(count) / SAMPLE_RATE
        u = np.clip(t / first_hit, 0, 1)
        grain = _band_noise(rng, first_hit, 190, 3400)
        wobble = .72 + .16 * np.sin(2 * np.pi * (5 * t + .7 * t ** 2))
        rolling = (.027 + .048 * np.sqrt(u)) * grain * wobble
        rolling += .006 * np.sin(2 * np.pi * (910 * t + 25 * t ** 2)) * np.sqrt(u)
        mix.add(_fade(rolling, .35, .03), 0, pan=-.48, label="Steel marble rolling on brass rails")

    # Most logs contain one event per newly moving domino. Deduplicate simultaneous
    # aliases, but never invent missing contact times to fill the five impacts.
    contact_times = sorted({_time(e) for e in domino_events})
    distinct = []
    for time in contact_times:
        if not distinct or time - distinct[-1] > .015:
            distinct.append(time)
    if not distinct or abs(distinct[0] - first_hit) > .015:
        distinct.insert(0, first_hit)
    if len(distinct) != 5:
        raise ValueError(f"Expected exactly five domino-contact cues, found {len(distinct)}: {distinct}")
    for index, time in enumerate(distinct):
        mix.add(_wood_clack(rng, index), time, level=.65, pan=-.32 + .12 * index, label=f"Domino {index + 1} contact")

    release = _first(events, ("counterweight_release", "weight_release", "sear_release", "latch_release"))
    gear_start = _first(events, ("gear_start",), release)
    bell_time = _first(events, ("bell_strike", "bell_impact", "hammer_bell", "bell_contact"))
    flag_time = _first(events, ("flag_release", "flag_unlatched"))
    if release is not None:
        mix.add(_metal_click(rng), release, level=.35, pan=.18, label="Counterweight sear release")
    if gear_start is not None and bell_time is not None and bell_time > gear_start:
        gear_end = _first(events, ("weight_stop", "counterweight_stop", "weight_landed", "counterweight_landed", "gear_stop"), bell_time + .25)
        length = max(.05, min(duration, gear_end) - gear_start)
        t = np.arange(int(length * SAMPLE_RATE)) / SAMPLE_RATE
        noise = _band_noise(rng, length, 300, 3800)
        gears = .035 * noise * (.65 + .35 * np.sin(2 * np.pi * 18.5 * t) ** 10)
        gears += .009 * np.sin(2 * np.pi * 142 * t) + .004 * np.sin(2 * np.pi * 307 * t)
        mix.add(_fade(gears, .10, .12), gear_start, pan=.22, label="Cord and meshing gears")

    if bell_time is None:
        raise ValueError("Missing physical hammer-to-bell contact event")
    mix.add(_bell(rng, min(7.5, duration - bell_time)), bell_time, level=.58, pan=.36, label="Hammer impact and bronze bell decay")
    if flag_time is None:
        raise ValueError("Missing bell-driven flag latch event")
    mix.add(_metal_click(rng, .12), flag_time, level=.17, pan=.48, label="Bell tab releases flag pawl")
    flag_length = min(.85, duration - flag_time)
    t = np.arange(int(flag_length * SAMPLE_RATE)) / SAMPLE_RATE
    envelope = np.sin(np.pi * np.clip(t / max(flag_length, .01), 0, 1)) ** 2
    cloth = _band_noise(rng, flag_length, 450, 6500) * envelope * .065
    cloth += .025 * np.sin(2 * np.pi * (360 * t - 80 * t ** 2)) * np.exp(-t / .22)
    mix.add(_fade(cloth, .025, .06), flag_time, pan=.5, label="Spring flag deployment and cloth rustle")

    return mix.finish(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--simulation", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("build/foley.wav"))
    parser.add_argument("--duration", type=float, default=DURATION)
    args = parser.parse_args()
    report = synthesize(json.loads(args.simulation.read_text()), args.output, args.duration)
    print(json.dumps({k: v for k, v in report.items() if k != "cues"}, indent=2))


if __name__ == "__main__":
    main()
