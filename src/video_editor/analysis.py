from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass(slots=True)
class DetectionConfig:
    static_seconds: float = 5.0
    sample_fps: float = 3.0
    resize_width: int = 640
    ssim_threshold: float = 0.98
    motion_threshold: float = 0.45
    cursor_threshold: float = 3.5
    min_keep_seconds: float = 0.25


@dataclass(slots=True)
class DetectionResult:
    keep_segments: list[tuple[float, float]]
    removed_segments: list[tuple[float, float]]
    duration_seconds: float
    sampled_frames: int


def analyze_video(video_path: str | Path, config: DetectionConfig) -> DetectionResult:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise ValueError(f"Unable to open video: {video_path}")

    try:
        native_fps = capture.get(cv2.CAP_PROP_FPS) or 0.0
        frame_count = capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
        if native_fps <= 0:
            native_fps = config.sample_fps
        duration_seconds = frame_count / native_fps if frame_count > 0 else 0.0
        sample_fps = max(config.sample_fps, 0.1)
        frame_interval = max(1, int(round(native_fps / sample_fps)))
        sample_period = 1.0 / sample_fps
        duration_epsilon = min(sample_period * 0.6, 0.5)

        prev_gray: np.ndarray | None = None
        prev_ts: float | None = None
        sampled_frames = 0
        static_start: float | None = None
        last_static_end: float | None = None
        static_break_count = 0
        static_anchor_gray: np.ndarray | None = None
        removed_segments: list[tuple[float, float]] = []
        frame_index = 0

        while True:
            ok, frame = capture.read()
            if not ok:
                break

            if frame_index % frame_interval != 0:
                frame_index += 1
                continue

            # Use frame-index based timing because CAP_PROP_POS_MSEC can be noisy/non-monotonic
            # on some codecs and may cause static durations to be undercounted.
            timestamp_seconds = frame_index / native_fps
            gray = _prepare_frame(frame, config.resize_width)
            sampled_frames += 1

            if prev_gray is not None and prev_ts is not None:
                similarity = _frame_similarity(prev_gray, gray)
                delta_ratio = _frame_delta_ratio(prev_gray, gray)
                changed_fraction = _changed_pixel_fraction(prev_gray, gray)

                # Fast early guards to avoid expensive flow calculations on clearly active frames.
                definitely_active = changed_fraction >= 0.020 or delta_ratio >= 0.030
                probable_ui_edit = (
                    changed_fraction >= 0.003
                    and delta_ratio >= 0.002
                    and changed_fraction <= 0.100
                    and similarity < max(config.ssim_threshold + 0.010, 0.992)
                )

                # A strict check plus fallback checks for highly similar/low-delta frames.
                # This helps avoid missing static spans due to tiny compression noise.
                is_static = False
                if not definitely_active and not probable_ui_edit:
                    strict_visual_static = (
                        similarity >= config.ssim_threshold
                        and delta_ratio <= 0.010
                        and changed_fraction <= 0.008
                    )
                    if strict_visual_static:
                        is_static = True
                    else:
                        motion = _global_motion(prev_gray, gray)
                        cursor_motion = _cursor_motion(prev_gray, gray)
                        is_static = (
                            similarity >= config.ssim_threshold
                            and motion <= config.motion_threshold
                            and cursor_motion <= config.cursor_threshold
                        )
                        if not is_static:
                            low_delta_threshold = max(0.006, min(0.02, (1.0 - config.ssim_threshold) * 2.0))
                            very_high_similarity = similarity >= max(config.ssim_threshold + 0.005, 0.992)
                            very_low_pixel_delta = delta_ratio <= 0.010
                            relaxed_motion = motion <= config.motion_threshold * 1.25
                            relaxed_cursor = cursor_motion <= config.cursor_threshold * 1.5

                            very_low_delta = delta_ratio <= 0.004
                            soft_motion = motion <= config.motion_threshold * 1.5
                            soft_cursor = cursor_motion <= config.cursor_threshold * 2.0

                            # Primary fallback for "looks identical for long spans" cases.
                            near_identical_frame = (
                                similarity >= config.ssim_threshold - 0.006
                                and delta_ratio <= low_delta_threshold
                                and changed_fraction <= 0.010
                                and motion <= config.motion_threshold * 1.8
                            )

                            mostly_unchanged_frame = (
                                similarity >= config.ssim_threshold - 0.004
                                and delta_ratio <= low_delta_threshold
                                and changed_fraction <= 0.008
                                and motion <= config.motion_threshold * 1.4
                                and cursor_motion <= config.cursor_threshold * 1.4
                            )

                            ultra_low_change_frame = (
                                changed_fraction <= 0.004
                                and delta_ratio <= 0.006
                                and similarity >= config.ssim_threshold - 0.006
                            )

                            is_static = (
                                near_identical_frame
                                or mostly_unchanged_frame
                                or ultra_low_change_frame
                                or (very_high_similarity and very_low_pixel_delta and relaxed_motion and relaxed_cursor)
                                or (very_low_delta and soft_motion and soft_cursor)
                            )

                # Guard against drift: adjacent frames may look similar while the scene
                # slowly changes over time. Compare against the static-run anchor frame.
                if is_static and static_anchor_gray is not None:
                    anchor_similarity = _frame_similarity(static_anchor_gray, gray)
                    anchor_delta = _frame_delta_ratio(static_anchor_gray, gray)
                    anchor_changed = _changed_pixel_fraction(static_anchor_gray, gray)
                    if (
                        anchor_similarity < (config.ssim_threshold - 0.010)
                        or anchor_delta > 0.020
                        or anchor_changed > 0.015
                    ):
                        is_static = False

                if is_static:
                    if static_start is None:
                        static_start = prev_ts
                        static_anchor_gray = prev_gray
                    last_static_end = timestamp_seconds
                    static_break_count = 0
                elif static_start is not None and last_static_end is not None:
                    # Allow one noisy sample before closing a static run.
                    static_break_count += 1
                    if static_break_count > 2:
                        if last_static_end - static_start >= max(0.0, config.static_seconds - duration_epsilon):
                            removed_segments.append((static_start, last_static_end))
                        static_start = None
                        last_static_end = None
                        static_anchor_gray = None
                        static_break_count = 0

            prev_gray = gray
            prev_ts = timestamp_seconds
            frame_index += 1

        if static_start is not None and last_static_end is not None:
            if last_static_end - static_start >= max(0.0, config.static_seconds - duration_epsilon):
                removed_segments.append((static_start, last_static_end))

        if duration_seconds <= 0 and prev_ts is not None:
            duration_seconds = prev_ts

        merged_removed = _merge_segments(removed_segments, gap_tolerance=sample_period * 2.0)
        retained_static_seconds = min(3.0, max(2.0, config.static_seconds * 0.5))
        compressed_removed = _compress_static_segments(merged_removed, retained_static_seconds)
        keep_segments = _invert_segments(compressed_removed, duration_seconds, config.min_keep_seconds)

        if not keep_segments and duration_seconds > 0:
            keep_segments = [(0.0, duration_seconds)]
            compressed_removed = []

        return DetectionResult(
            keep_segments=keep_segments,
            removed_segments=compressed_removed,
            duration_seconds=duration_seconds,
            sampled_frames=sampled_frames,
        )
    finally:
        capture.release()


def _prepare_frame(frame: np.ndarray, resize_width: int) -> np.ndarray:
    height, width = frame.shape[:2]
    if width > resize_width:
        scale = resize_width / width
        resized = cv2.resize(frame, (resize_width, max(1, int(height * scale))), interpolation=cv2.INTER_AREA)
    else:
        resized = frame
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    return cv2.GaussianBlur(gray, (5, 5), 0)


def _frame_similarity(previous_gray: np.ndarray, current_gray: np.ndarray) -> float:
    previous = previous_gray.astype(np.float32)
    current = current_gray.astype(np.float32)
    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2

    mu_previous = cv2.GaussianBlur(previous, (11, 11), 1.5)
    mu_current = cv2.GaussianBlur(current, (11, 11), 1.5)

    mu_previous_sq = mu_previous * mu_previous
    mu_current_sq = mu_current * mu_current
    mu_product = mu_previous * mu_current

    sigma_previous_sq = cv2.GaussianBlur(previous * previous, (11, 11), 1.5) - mu_previous_sq
    sigma_current_sq = cv2.GaussianBlur(current * current, (11, 11), 1.5) - mu_current_sq
    sigma_product = cv2.GaussianBlur(previous * current, (11, 11), 1.5) - mu_product

    numerator = (2 * mu_product + c1) * (2 * sigma_product + c2)
    denominator = (mu_previous_sq + mu_current_sq + c1) * (sigma_previous_sq + sigma_current_sq + c2)
    ssim_map = numerator / (denominator + 1e-8)
    return float(np.clip(ssim_map.mean(), 0.0, 1.0))


def _frame_delta_ratio(previous_gray: np.ndarray, current_gray: np.ndarray) -> float:
    diff = cv2.absdiff(previous_gray, current_gray)
    return float(np.mean(diff) / 255.0)


def _changed_pixel_fraction(previous_gray: np.ndarray, current_gray: np.ndarray, threshold: int = 8) -> float:
    diff = cv2.absdiff(previous_gray, current_gray)
    changed = diff > threshold
    return float(np.count_nonzero(changed) / changed.size)


def _global_motion(previous_gray: np.ndarray, current_gray: np.ndarray) -> float:
    flow = cv2.calcOpticalFlowFarneback(
        previous_gray,
        current_gray,
        None,
        pyr_scale=0.5,
        levels=3,
        winsize=15,
        iterations=3,
        poly_n=5,
        poly_sigma=1.2,
        flags=0,
    )
    magnitude = cv2.magnitude(flow[..., 0], flow[..., 1])
    return float(np.mean(magnitude))


def _cursor_motion(previous_gray: np.ndarray, current_gray: np.ndarray) -> float:
    features = cv2.goodFeaturesToTrack(previous_gray, maxCorners=50, qualityLevel=0.01, minDistance=10)
    if features is None:
        return 0.0

    next_points, status, _ = cv2.calcOpticalFlowPyrLK(previous_gray, current_gray, features, None)
    if next_points is None or status is None:
        return 0.0

    valid = status.flatten() == 1
    if not np.any(valid):
        return 0.0

    previous_points = features[valid][:, 0, :]
    current_points = next_points[valid][:, 0, :]
    displacement = np.linalg.norm(current_points - previous_points, axis=1)
    return float(np.percentile(displacement, 75))


def _merge_segments(segments: list[tuple[float, float]], gap_tolerance: float) -> list[tuple[float, float]]:
    if not segments:
        return []

    sorted_segments = sorted(segments)
    merged = [sorted_segments[0]]
    for start, end in sorted_segments[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end + gap_tolerance:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _invert_segments(
    removed_segments: list[tuple[float, float]],
    duration_seconds: float,
    min_keep_seconds: float,
) -> list[tuple[float, float]]:
    if duration_seconds <= 0:
        return []

    keep_segments: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in removed_segments:
        start = max(0.0, min(start, duration_seconds))
        end = max(0.0, min(end, duration_seconds))
        if start - cursor >= min_keep_seconds:
            keep_segments.append((cursor, start))
        cursor = max(cursor, end)

    if duration_seconds - cursor >= min_keep_seconds:
        keep_segments.append((cursor, duration_seconds))
    return keep_segments


def _compress_static_segments(
    removed_segments: list[tuple[float, float]],
    retained_static_seconds: float,
) -> list[tuple[float, float]]:
    if not removed_segments:
        return []

    keep_per_static = max(0.1, float(retained_static_seconds))
    compressed: list[tuple[float, float]] = []
    for start, end in removed_segments:
        duration = max(0.0, end - start)
        if duration <= keep_per_static:
            continue

        edge_keep = keep_per_static / 2.0
        remove_start = start + edge_keep
        remove_end = end - edge_keep
        if remove_end - remove_start >= 0.05:
            compressed.append((remove_start, remove_end))

    return compressed
