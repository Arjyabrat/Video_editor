from __future__ import annotations

import multiprocessing
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4
import sys

from .analysis import DetectionConfig, analyze_video
from .ffmpeg_tools import normalize_input_video, render_trimmed_video


def _log(msg: str) -> None:
    print(f"[VIDEO-EDITOR] {msg}", file=sys.stderr, flush=True)


# Resolve storage paths from repository root so worker processes are cwd-independent.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
STORAGE_ROOT = PROJECT_ROOT / "storage"
UPLOAD_ROOT = STORAGE_ROOT / "uploads"
OUTPUT_ROOT = STORAGE_ROOT / "outputs"


@dataclass(slots=True)
class ProcessingJob:
    job_id: str
    status: str
    message: str
    input_name: str
    output_name: str | None = None
    error: str | None = None
    details: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def ensure_storage() -> None:
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)


def build_job(input_name: str) -> ProcessingJob:
    return ProcessingJob(
        job_id=uuid4().hex,
        status="queued",
        message="Waiting to start.",
        input_name=input_name,
    )


def save_upload(source_file, filename: str) -> Path:
    ensure_storage()
    safe_name = Path(filename).name or "input-video"
    suffix = Path(safe_name).suffix or ".mp4"
    target = UPLOAD_ROOT / f"{uuid4().hex}{suffix}"
    with target.open("wb") as output_stream:
        shutil.copyfileobj(source_file, output_stream)
    return target.resolve()


def process_video(
    job: ProcessingJob,
    input_path: Path,
    config: DetectionConfig,
    export_speed: float = 1.0,
    export_quality: str = "720p",
) -> ProcessingJob:
    ensure_storage()
    job.status = "processing"
    job.message = "Analyzing frames for static spans."
    _log(f"Starting job {job.job_id}: {input_path}")

    try:
        detection = analyze_video(input_path, config)
        _log(f"Analysis complete: {detection.sampled_frames} frames, {len(detection.removed_segments)} static segments")
    except Exception as e:
        job.status = "failed"
        job.message = "Frame analysis failed."
        job.error = str(e)
        _log(f"Analysis error in job {job.job_id}: {e}")
        return job

    output_name = f"{job.job_id}.mp4"
    output_path = OUTPUT_ROOT / output_name

    job.message = "Rendering trimmed output."
    _log(f"Rendering output for job {job.job_id}: {len(detection.keep_segments)} segments to keep")
    
    try:
        render_trimmed_video(
            input_path,
            output_path,
            detection.keep_segments,
            playback_speed=export_speed,
            export_quality=export_quality,
        )
        _log(f"Rendering complete for job {job.job_id}: {output_path}")
    except Exception as e:
        job.status = "failed"
        job.message = "Video rendering failed."
        job.error = str(e)
        _log(f"Rendering error in job {job.job_id}: {e}")
        return job

    job.status = "completed"
    job.message = "Video is ready to download."
    job.output_name = output_name
    job.details = {
        "duration_seconds": round(detection.duration_seconds, 2),
        "sampled_frames": detection.sampled_frames,
        "export_speed": export_speed,
        "export_quality": export_quality,
        "removed_segments": [
            {"start": round(start, 2), "end": round(end, 2), "duration": round(end - start, 2)}
            for start, end in detection.removed_segments
        ],
        "keep_segments": [
            {"start": round(start, 2), "end": round(end, 2), "duration": round(end - start, 2)}
            for start, end in detection.keep_segments
        ],
    }
    _log(f"Job {job.job_id} completed successfully")
    return job


def process_video_isolated(
    job: ProcessingJob,
    input_path: Path,
    config: DetectionConfig,
    export_speed: float = 1.0,
    export_quality: str = "720p",
    timeout_seconds: float = 1200.0,
) -> ProcessingJob:
    """Run processing in a child process to protect the API process from native crashes."""

    ensure_storage()
    job.status = "processing"
    job.message = "Analyzing frames for static spans."

    ctx = multiprocessing.get_context("spawn")
    result_queue: multiprocessing.Queue = ctx.Queue(maxsize=1)

    child = ctx.Process(
        target=_process_video_child,
        args=(
            str(input_path),
            config.static_seconds,
            config.sample_fps,
            config.resize_width,
            config.ssim_threshold,
            config.motion_threshold,
            config.cursor_threshold,
            config.min_keep_seconds,
            export_speed,
            export_quality,
            str(OUTPUT_ROOT),
            job.job_id,
            result_queue,
        ),
        daemon=True,
    )
    child.start()
    child.join(timeout_seconds)

    if child.is_alive():
        child.terminate()
        child.join(5)
        job.status = "failed"
        job.message = "Processing timed out."
        job.error = f"Job exceeded timeout of {int(timeout_seconds)} seconds."
        return job

    if child.exitcode != 0:
        _log(f"Worker exitcode={child.exitcode}; retrying job {job.job_id} in-process")
        try:
            # Fallback path: run in-process so users are not blocked by spawn/reload issues.
            return process_video(job, input_path, config, export_speed, export_quality)
        except Exception as exc:
            job.status = "failed"
            job.message = "Processing failed after worker crash."
            job.error = f"Worker crashed (exit code {child.exitcode}) and fallback failed: {exc}"
            return job

    try:
        result = result_queue.get_nowait()
    except Exception:
        _log(f"Worker returned no result for job {job.job_id}; retrying in-process")
        try:
            return process_video(job, input_path, config, export_speed, export_quality)
        except Exception as exc:
            job.status = "failed"
            job.message = "Processing failed."
            job.error = f"Worker did not return a result; fallback failed: {exc}"
            return job

    job.status = result.get("status", "failed")
    job.message = result.get("message", "Processing failed.")
    job.error = result.get("error")
    job.output_name = result.get("output_name")
    job.details = result.get("details")
    return job


def _is_under_sampled(detection, sample_fps: float) -> bool:
    expected_samples = detection.duration_seconds * max(sample_fps, 0.1)
    minimum_reasonable = max(10, int(expected_samples * 0.35))
    return detection.sampled_frames < minimum_reasonable


def _removed_ratio(detection) -> float:
    if detection.duration_seconds <= 0:
        return 0.0
    removed_total = sum(max(0.0, end - start) for start, end in detection.removed_segments)
    return min(1.0, removed_total / detection.duration_seconds)


def _process_video_child(
    input_path: str,
    static_seconds: float,
    sample_fps: float,
    resize_width: int,
    ssim_threshold: float,
    motion_threshold: float,
    cursor_threshold: float,
    min_keep_seconds: float,
    export_speed: float,
    export_quality: str,
    output_root: str,
    job_id: str,
    result_queue,
) -> None:
    try:
        config = DetectionConfig(
            static_seconds=static_seconds,
            sample_fps=sample_fps,
            resize_width=resize_width,
            ssim_threshold=ssim_threshold,
            motion_threshold=motion_threshold,
            cursor_threshold=cursor_threshold,
            min_keep_seconds=min_keep_seconds,
        )
        source_input = Path(input_path)
        analysis_input = source_input
        with tempfile.TemporaryDirectory(prefix="video-editor-input-") as temp_dir_name:
            temp_dir = Path(temp_dir_name)

            detection = analyze_video(analysis_input, config)
            if _is_under_sampled(detection, config.sample_fps):
                analysis_proxy = temp_dir / "analysis-proxy.mp4"
                normalize_input_video(
                    source_input,
                    analysis_proxy,
                    target_fps=max(6.0, config.sample_fps * 2.0),
                    target_height=360,
                    preset="ultrafast",
                    crf=30,
                    include_audio=False,
                )
                analysis_input = analysis_proxy
                detection = analyze_video(analysis_input, config)

                # If normalized pass becomes too aggressive, retry with stricter thresholds.
                if _removed_ratio(detection) > 0.90:
                    strict_config = DetectionConfig(
                        static_seconds=config.static_seconds,
                        sample_fps=config.sample_fps,
                        resize_width=config.resize_width,
                        ssim_threshold=min(0.995, config.ssim_threshold + 0.01),
                        motion_threshold=max(0.10, config.motion_threshold * 0.75),
                        cursor_threshold=max(1.0, config.cursor_threshold * 0.75),
                        min_keep_seconds=config.min_keep_seconds,
                    )
                    strict_detection = analyze_video(analysis_input, strict_config)
                    if _removed_ratio(strict_detection) < _removed_ratio(detection):
                        detection = strict_detection

            output_name = f"{job_id}.mp4"
            output_path = Path(output_root) / output_name
            render_trimmed_video(
                source_input,
                output_path,
                detection.keep_segments,
                playback_speed=export_speed,
                export_quality=export_quality,
            )

        result_queue.put(
            {
                "status": "completed",
                "message": "Video is ready to download.",
                "output_name": output_name,
                "details": {
                    "duration_seconds": round(detection.duration_seconds, 2),
                    "sampled_frames": detection.sampled_frames,
                    "export_speed": export_speed,
                    "export_quality": export_quality,
                    "removed_segments": [
                        {"start": round(start, 2), "end": round(end, 2), "duration": round(end - start, 2)}
                        for start, end in detection.removed_segments
                    ],
                    "keep_segments": [
                        {"start": round(start, 2), "end": round(end, 2), "duration": round(end - start, 2)}
                        for start, end in detection.keep_segments
                    ],
                },
            }
        )
    except Exception as exc:
        result_queue.put(
            {
                "status": "failed",
                "message": "Video processing failed.",
                "error": str(exc),
            }
        )
