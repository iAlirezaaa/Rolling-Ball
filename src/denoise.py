"""Optional CPU denoising with the official Intel Open Image Denoise library.

Install the official OIDN binary release separately and pass its shared library
path with --library (or OIDN_LIBRARY). No third-party binaries are stored here.
PNG input is explicitly treated as sRGB LDR; the film's AgX transform is already
baked by Blender. OIDN's RT filter operates on each complete frame, never mixes
frames, and therefore cannot produce motion trails or invent intermediate motion.
"""
from __future__ import annotations

import argparse
import ctypes as C
import glob
import json
import os
import time
from pathlib import Path

import numpy as np
from PIL import Image


class Denoiser:
    def __init__(self, library: str, threads: int = 0):
        self.lib = C.CDLL(library)
        L = self.lib
        signatures = {
            "oidnNewDevice": ([C.c_int], C.c_void_p),
            "oidnSetDeviceInt": ([C.c_void_p, C.c_char_p, C.c_int], None),
            "oidnCommitDevice": ([C.c_void_p], None),
            "oidnGetDeviceError": ([C.c_void_p, C.POINTER(C.c_char_p)], C.c_int),
            "oidnNewFilter": ([C.c_void_p, C.c_char_p], C.c_void_p),
            "oidnSetSharedFilterImage": ([C.c_void_p, C.c_char_p, C.c_void_p, C.c_int,
                                          C.c_size_t, C.c_size_t, C.c_size_t,
                                          C.c_size_t, C.c_size_t], None),
            "oidnSetFilterBool": ([C.c_void_p, C.c_char_p, C.c_bool], None),
            "oidnCommitFilter": ([C.c_void_p], None),
            "oidnExecuteFilter": ([C.c_void_p], None),
            "oidnReleaseFilter": ([C.c_void_p], None),
            "oidnReleaseDevice": ([C.c_void_p], None),
        }
        for name, (args, result) in signatures.items():
            f = getattr(L, name); f.argtypes = args; f.restype = result
        self.device = L.oidnNewDevice(1)  # OIDN_DEVICE_TYPE_CPU
        if not self.device:
            raise RuntimeError("OIDN could not create a CPU device")
        if threads > 0:
            L.oidnSetDeviceInt(self.device, b"numThreads", threads)
        L.oidnCommitDevice(self.device)
        self._check()
        self.filter = L.oidnNewFilter(self.device, b"RT")
        L.oidnSetFilterBool(self.filter, b"hdr", False)
        L.oidnSetFilterBool(self.filter, b"srgb", True)

    def _check(self):
        message = C.c_char_p()
        error = self.lib.oidnGetDeviceError(self.device, C.byref(message))
        if error:
            raise RuntimeError(f"OIDN error {error}: {message.value.decode() if message.value else 'unknown'}")

    def apply(self, rgb: np.ndarray) -> np.ndarray:
        src = np.ascontiguousarray(rgb, dtype=np.float32)
        if src.ndim != 3 or src.shape[2] != 3:
            raise ValueError("Expected an H×W×3 RGB array")
        dst = np.empty_like(src)
        height, width, _ = src.shape
        for name, array in [(b"color", src), (b"output", dst)]:
            self.lib.oidnSetSharedFilterImage(self.filter, name, C.c_void_p(array.ctypes.data),
                                             3, width, height, 0, 12, width * 12)
        self.lib.oidnCommitFilter(self.filter)
        self._check()
        self.lib.oidnExecuteFilter(self.filter)
        self._check()
        return np.clip(dst, 0, 1)

    def close(self):
        self.lib.oidnReleaseFilter(self.filter)
        self.lib.oidnReleaseDevice(self.device)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="PNG path or shell glob (quote it)")
    parser.add_argument("--output", required=True, help="Output directory")
    parser.add_argument("--library", default=os.environ.get("OIDN_LIBRARY"))
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--blend", type=float, default=1.0, help="Denoised amount [0,1]")
    parser.add_argument("--skip-existing", action="store_true")
    args = parser.parse_args()
    if not args.library:
        parser.error("Pass --library /path/to/libOpenImageDenoise.so or set OIDN_LIBRARY")
    if not 0 <= args.blend <= 1:
        parser.error("--blend must be between 0 and 1")
    files = [Path(p) for p in sorted(glob.glob(args.input))]
    if not files:
        parser.error(f"No inputs matched {args.input!r}")
    dest = Path(args.output); dest.mkdir(parents=True, exist_ok=True)
    denoiser = Denoiser(args.library, args.threads)
    t0 = time.perf_counter(); count = 0
    try:
        for source in files:
            target = dest / source.name
            if target.resolve() == source.resolve():
                raise ValueError("Output must not overwrite the source frame")
            if args.skip_existing and target.exists():
                continue
            with Image.open(source) as im:
                rgb = np.asarray(im.convert("RGB"), dtype=np.float32) / 255
            filtered = denoiser.apply(rgb)
            final = args.blend * filtered + (1 - args.blend) * rgb
            Image.fromarray(np.uint8(np.rint(np.clip(final, 0, 1) * 255))).save(target)
            count += 1
            if count == 1 or count % 25 == 0:
                print(f"Denoised {count}/{len(files)} frames in {time.perf_counter()-t0:.2f}s", flush=True)
    finally:
        denoiser.close()
    report = {"frames_processed": count, "method": "Intel Open Image Denoise RT / sRGB LDR",
              "temporal_mixing": False, "blend": args.blend,
              "seconds": round(time.perf_counter() - t0, 3)}
    (dest / "denoise-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
