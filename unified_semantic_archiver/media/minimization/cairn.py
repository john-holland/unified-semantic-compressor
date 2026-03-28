from __future__ import annotations

import hashlib
import json
import subprocess
import zlib
from array import array
from pathlib import Path
from typing import Any


def _run_ffmpeg_decode_s16_mono(path: Path, sample_rate: int) -> array:
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-i",
        str(path),
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-f",
        "s16le",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, check=True, timeout=120)
    pcm = array("h")
    pcm.frombytes(proc.stdout)
    return pcm


def _windowed(samples: array, window_size: int, hop_size: int) -> list[array]:
    out: list[array] = []
    if not samples:
        return out
    i = 0
    n = len(samples)
    while i < n:
        j = min(n, i + window_size)
        out.append(samples[i:j])
        if j == n:
            break
        i += hop_size
    return out


def _descriptor(win: array) -> dict[str, float]:
    if not win:
        return {"pitch_norm": 0.0, "energy_norm": 0.0, "flux_norm": 0.0}
    abs_sum = 0.0
    zc = 0
    flux = 0.0
    prev = int(win[0])
    for i, v in enumerate(win):
        x = int(v)
        abs_sum += abs(x)
        if i > 0:
            if (x >= 0 > prev) or (x < 0 <= prev):
                zc += 1
            flux += abs(x - prev)
        prev = x
    energy = abs_sum / (len(win) * 32768.0)
    zcr = zc / max(1, len(win) - 1)
    flux_n = flux / (len(win) * 65536.0)
    return {
        "pitch_norm": max(0.0, min(1.0, zcr * 2.5)),
        "energy_norm": max(0.0, min(1.0, energy)),
        "flux_norm": max(0.0, min(1.0, flux_n)),
    }


def _planar_division(desc: dict[str, float]) -> int:
    # Coarse planar partition over descriptor space.
    a = 1 if (desc["pitch_norm"] + 0.6 * desc["energy_norm"]) >= 0.45 else 0
    b = 1 if (desc["flux_norm"] - 0.4 * desc["energy_norm"]) >= 0.15 else 0
    return (a << 1) | b


def _stone_path(desc: dict[str, float], max_depth: int) -> str:
    p = desc["pitch_norm"]
    e = desc["energy_norm"]
    f = desc["flux_norm"]
    path: list[str] = []
    for depth in range(max_depth):
        thr = 0.4 + (depth * 0.1)
        if p >= thr and e >= thr:
            q = 0
        elif p >= thr and e < thr:
            q = 1
        elif p < thr and e >= thr:
            q = 2
        else:
            q = 3 if f < 0.5 else 1
        path.append(str(q))
        # Mild deterministic transform so deeper splits vary.
        p = (p * 0.7 + f * 0.3)
        e = (e * 0.75 + (1.0 - f) * 0.25)
    return "".join(path)


def build_cairn_stones(
    audio_path: Path,
    *,
    sample_rate: int = 16000,
    window_ms: int = 32,
    hop_ms: int = 16,
    max_depth: int = 3,
) -> list[dict[str, Any]]:
    samples = _run_ffmpeg_decode_s16_mono(audio_path, sample_rate=sample_rate)
    window_size = max(64, int(sample_rate * (window_ms / 1000.0)))
    hop_size = max(32, int(sample_rate * (hop_ms / 1000.0)))
    wins = _windowed(samples, window_size, hop_size)
    stones: list[dict[str, Any]] = []
    for idx, win in enumerate(wins):
        d = _descriptor(win)
        plane = _planar_division(d)
        stones.append(
            {
                "index": idx,
                "start_ms": idx * hop_ms,
                "plane_id": plane,
                "stone_path": _stone_path(d, max_depth=max_depth),
                "pitch_norm": d["pitch_norm"],
                "energy_norm": d["energy_norm"],
                "flux_norm": d["flux_norm"],
            }
        )
    return stones


def _zigzag_encode(value: int) -> int:
    return (value << 1) ^ (value >> 31)


def _zigzag_decode(value: int) -> int:
    return (value >> 1) ^ -(value & 1)


def _varint_encode(value: int) -> bytes:
    out = bytearray()
    v = int(value)
    while v >= 0x80:
        out.append((v & 0x7F) | 0x80)
        v >>= 7
    out.append(v & 0x7F)
    return bytes(out)


def _varint_decode(buf: bytes, start: int) -> tuple[int, int]:
    shift = 0
    value = 0
    i = start
    while i < len(buf):
        b = buf[i]
        value |= (b & 0x7F) << shift
        i += 1
        if (b & 0x80) == 0:
            return value, i
        shift += 7
    raise ValueError("Invalid varint stream")


def build_residual_stream(
    original_stones: list[dict[str, Any]],
    generated_stones: list[dict[str, Any]],
    *,
    deadzone_q: int = 2,
) -> dict[str, Any]:
    n = min(len(original_stones), len(generated_stones))
    rows: list[tuple[int, int, int, int, int]] = []
    for i in range(n):
        a = original_stones[i]
        b = generated_stones[i]
        dp = int(a["plane_id"]) - int(b["plane_id"])
        pitch_q = int(round((float(a["pitch_norm"]) - float(b["pitch_norm"])) * 1000))
        energy_q = int(round((float(a["energy_norm"]) - float(b["energy_norm"])) * 1000))
        flux_q = int(round((float(a["flux_norm"]) - float(b["flux_norm"])) * 1000))
        if abs(pitch_q) <= deadzone_q:
            pitch_q = 0
        if abs(energy_q) <= deadzone_q:
            energy_q = 0
        if abs(flux_q) <= deadzone_q:
            flux_q = 0
        stone_delta = len(str(a["stone_path"])) - len(str(b["stone_path"]))
        rows.append((dp, pitch_q, energy_q, flux_q, stone_delta))

    # RLE runs by identical plane delta for tighter packing.
    packed = bytearray()
    packed.extend(_varint_encode(n))
    i = 0
    while i < n:
        dp = rows[i][0]
        run = 1
        while i + run < n and rows[i + run][0] == dp and run < 65535:
            run += 1
        packed.extend(_varint_encode(run))
        packed.extend(_varint_encode(_zigzag_encode(dp)))
        for j in range(i, i + run):
            _, p, e, f, s = rows[j]
            packed.extend(_varint_encode(_zigzag_encode(p)))
            packed.extend(_varint_encode(_zigzag_encode(e)))
            packed.extend(_varint_encode(_zigzag_encode(f)))
            packed.extend(_varint_encode(_zigzag_encode(s)))
        i += run

    compressed = zlib.compress(bytes(packed), level=9)
    digest = hashlib.sha256(compressed).hexdigest()
    return {
        "schema": "cairn_residual_v1",
        "count": n,
        "deadzone_q": deadzone_q,
        "payload": compressed,
        "sha256": digest,
    }


def decode_residual_stream(payload: bytes) -> list[tuple[int, int, int, int, int]]:
    raw = zlib.decompress(payload)
    n, idx = _varint_decode(raw, 0)
    out: list[tuple[int, int, int, int, int]] = []
    while len(out) < n:
        run, idx = _varint_decode(raw, idx)
        dp_zz, idx = _varint_decode(raw, idx)
        dp = _zigzag_decode(dp_zz)
        for _ in range(run):
            p_zz, idx = _varint_decode(raw, idx)
            e_zz, idx = _varint_decode(raw, idx)
            f_zz, idx = _varint_decode(raw, idx)
            s_zz, idx = _varint_decode(raw, idx)
            out.append((dp, _zigzag_decode(p_zz), _zigzag_decode(e_zz), _zigzag_decode(f_zz), _zigzag_decode(s_zz)))
    return out


def write_cairn_sidecars(
    *,
    original_audio_path: Path,
    generated_audio_path: Path | None,
    out_dir: Path,
    max_depth: int = 3,
     write_debug_json: bool = False,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    orig = build_cairn_stones(original_audio_path, max_depth=max_depth)
    if generated_audio_path and generated_audio_path.is_file():
        try:
            gen = build_cairn_stones(generated_audio_path, max_depth=max_depth)
        except Exception:
            gen = [{"plane_id": 0, "stone_path": "", "pitch_norm": 0.0, "energy_norm": 0.0, "flux_norm": 0.0} for _ in orig]
    else:
        gen = [{"plane_id": 0, "stone_path": "", "pitch_norm": 0.0, "energy_norm": 0.0, "flux_norm": 0.0} for _ in orig]

    residual = build_residual_stream(orig, gen)

    json_path = out_dir / "audio.cairn.json"
    bin_path = out_dir / "audio.cairn.residual.bin"
    meta_path = out_dir / "audio.cairn.residual.meta.json"

    json_payload = {
        "schema": "cairn_audio_v1",
        "original_audio": str(original_audio_path),
        "generated_audio": str(generated_audio_path) if generated_audio_path else None,
        "stones": orig,
    }
    if write_debug_json:
        json_path.write_text(json.dumps(json_payload, indent=2), encoding="utf-8")
    bin_path.write_bytes(residual["payload"])
    meta_path.write_text(
        json.dumps(
            {
                "schema": residual["schema"],
                "count": residual["count"],
                "deadzone_q": residual["deadzone_q"],
                "sha256": residual["sha256"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "json_path": str(json_path) if write_debug_json else None,
        "residual_bin_path": str(bin_path),
        "residual_meta_path": str(meta_path),
        "stone_count": len(orig),
        "residual_count": residual["count"],
        "debug_json_written": write_debug_json,
    }
