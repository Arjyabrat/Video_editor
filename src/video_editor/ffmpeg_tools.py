from __future__ import annotations

import subprocess
from pathlib import Path

import imageio_ffmpeg


QUALITY_PROFILES: dict[str, dict[str, int | None]] = {
    "original": {"height": None, "crf": 18},
    "1080p": {"height": 1080, "crf": 18},
    "720p": {"height": 720, "crf": 20},
    "480p": {"height": 480, "crf": 22},
}


def normalize_input_video(
    input_path: str | Path,
    output_path: str | Path,
    *,
    target_fps: float = 30.0,
    target_height: int | None = None,
    preset: str = "superfast",
    crf: int = 20,
    include_audio: bool = True,
) -> None:
    """Re-encode source video to a stable MP4 for OpenCV analysis/rendering."""
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    input_path = Path(input_path).resolve()
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    command = [
        ffmpeg_exe,
        "-y",
        "-i",
        str(input_path),
        "-fps_mode",
        "cfr",
        "-r",
        f"{target_fps:.3f}",
    ]

    if target_height is not None and target_height > 0:
        command.extend(["-vf", f"scale=-2:{int(target_height)}"])

    command.extend([
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        str(crf),
    ])

    if include_audio:
        command.extend(["-c:a", "aac"])
    else:
        command.append("-an")

    command.extend([
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_path),
    ])
    _run(command, timeout_seconds=900)


def render_trimmed_video(
    input_path: str | Path,
    output_path: str | Path,
    segments: list[tuple[float, float]],
    *,
    playback_speed: float = 1.0,
    export_quality: str = "720p",
) -> None:
    if not segments:
        raise ValueError("No segments were selected for output.")

    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    input_path = Path(input_path).resolve()
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    profile = _quality_profile(export_quality)
    speed = max(0.25, float(playback_speed or 1.0))
    has_audio = _has_audio_stream(input_path)
    filter_parts: list[str] = []

    if has_audio:
        concat_inputs: list[str] = []
        for index, (start, end) in enumerate(segments):
            start_s = max(0.0, float(start))
            end_s = max(start_s + 0.05, float(end))
            v_label = f"v{index}"
            a_label = f"a{index}"
            filter_parts.append(f"[0:v]trim=start={start_s:.6f}:end={end_s:.6f},setpts=PTS-STARTPTS[{v_label}]")
            filter_parts.append(f"[0:a]atrim=start={start_s:.6f}:end={end_s:.6f},asetpts=PTS-STARTPTS[{a_label}]")
            concat_inputs.append(f"[{v_label}][{a_label}]")
        filter_parts.append("".join(concat_inputs) + f"concat=n={len(segments)}:v=1:a=1[vcat][acat]")
    else:
        concat_inputs = []
        for index, (start, end) in enumerate(segments):
            start_s = max(0.0, float(start))
            end_s = max(start_s + 0.05, float(end))
            v_label = f"v{index}"
            filter_parts.append(f"[0:v]trim=start={start_s:.6f}:end={end_s:.6f},setpts=PTS-STARTPTS[{v_label}]")
            concat_inputs.append(f"[{v_label}]")
        filter_parts.append("".join(concat_inputs) + f"concat=n={len(segments)}:v=1:a=0[vcat]")

    video_filters: list[str] = []
    if profile["height"] is not None:
        video_filters.append(f"scale=-2:{int(profile['height'])}")
    if speed != 1.0:
        video_filters.append(f"setpts=PTS/{speed:.6f}")
    if video_filters:
        filter_parts.append(f"[vcat]{','.join(video_filters)}[vout]")
    else:
        filter_parts.append("[vcat]null[vout]")

    if has_audio:
        if speed != 1.0:
            filter_parts.append(f"[acat]{_build_atempo_chain(speed)}[aout]")
        else:
            filter_parts.append("[acat]anull[aout]")

    command = [
        ffmpeg_exe,
        "-y",
        "-i",
        str(input_path),
        "-filter_complex",
        ";".join(filter_parts),
        "-map",
        "[vout]",
    ]

    if has_audio:
        command.extend(["-map", "[aout]", "-c:a", "aac"])
    else:
        command.append("-an")

    command.extend([
        "-fps_mode",
        "cfr",
        "-r",
        "30",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        str(profile["crf"]),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_path),
    ])
    _run(command, timeout_seconds=900)


def _run(command: list[str], timeout_seconds: int | None = None) -> None:
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout_seconds)
    if result.returncode != 0:
        details = result.stderr.strip() or result.stdout.strip() or "ffmpeg failed without diagnostics"
        raise RuntimeError(details)


def _quality_profile(name: str) -> dict[str, int | None]:
    return QUALITY_PROFILES.get((name or "720p").lower(), QUALITY_PROFILES["720p"])


def _has_audio_stream(input_path: Path) -> bool:
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    probe = subprocess.run([ffmpeg_exe, "-i", str(input_path)], capture_output=True, text=True)
    combined = (probe.stderr or "") + "\n" + (probe.stdout or "")
    return "Audio:" in combined


def _build_atempo_chain(speed: float) -> str:
    speed = max(0.25, float(speed or 1.0))
    filters: list[str] = []
    remaining = speed
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining *= 2.0
    filters.append(f"atempo={remaining:.6f}")
    return ",".join(filters)
