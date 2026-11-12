import cv2
import numpy as np


MAX_REVIEW_ROTATION_DEG = 12.0
MAX_REVIEW_TRANSLATION_M = 0.05


def pose_delta(reference, candidate):
    reference = np.asarray(reference, dtype=float)
    candidate = np.asarray(candidate, dtype=float)
    delta = np.linalg.inv(reference) @ candidate
    cosine = np.clip((np.trace(delta[:3, :3]) - 1) / 2, -1, 1)
    return float(np.linalg.norm(delta[:3, 3])), float(np.degrees(np.arccos(cosine)))


def depth_alignment(rendered_depth, measured_depth, min_pixels=128, tolerance_m=0.02,
                    max_median_error_m=0.015, min_inlier_ratio=0.65):
    rendered_depth = np.asarray(rendered_depth)
    measured_depth = np.asarray(measured_depth)
    interior = cv2.erode((rendered_depth > 0.001).astype(np.uint8), np.ones((3, 3), np.uint8))
    valid = (interior > 0) & (measured_depth > 0.001)
    pixels = int(np.count_nonzero(valid))
    if pixels < min_pixels:
        return {"accepted": False, "depth_pixels": pixels,
                "depth_median_error_mm": None, "depth_inlier_ratio": None}
    errors = np.abs(rendered_depth[valid] - measured_depth[valid])
    median_error = float(np.median(errors))
    inlier_ratio = float(np.mean(errors <= tolerance_m))
    return {"accepted": bool(median_error <= max_median_error_m
                             and inlier_ratio >= min_inlier_ratio),
            "depth_pixels": pixels, "depth_median_error_mm": median_error * 1000,
            "depth_inlier_ratio": inlier_ratio, "depth_inlier_tolerance_mm": tolerance_m * 1000}
