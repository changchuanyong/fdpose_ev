from __future__ import annotations

import unittest

try:
    import numpy as np
except ModuleNotFoundError:
    np = None

if np is not None:
    from apps.pose_checks import depth_alignment, pose_delta


@unittest.skipIf(np is None, "NumPy is unavailable in the standard-library-only smoke environment")
class PoseChecksTest(unittest.TestCase):
    def test_pose_delta_detects_rotation_and_translation(self) -> None:
        reference = np.eye(4)
        candidate = np.eye(4)
        angle = np.deg2rad(29)
        candidate[:3, :3] = [[np.cos(angle), -np.sin(angle), 0],
                             [np.sin(angle), np.cos(angle), 0], [0, 0, 1]]
        candidate[:3, 3] = [0.01, -0.02, 0.03]
        translation, rotation = pose_delta(reference, candidate)
        self.assertAlmostEqual(0.0374166, translation, places=5)
        self.assertAlmostEqual(29, rotation, places=5)

    def test_depth_alignment_accepts_matching_surface(self) -> None:
        rendered = np.full((40, 40), 0.5, dtype=np.float32)
        measured = rendered.copy()
        result = depth_alignment(rendered, measured)
        self.assertTrue(result["accepted"])
        self.assertEqual(0, result["depth_median_error_mm"])
        self.assertEqual(1, result["depth_inlier_ratio"])

    def test_depth_alignment_rejects_tilted_surface(self) -> None:
        rendered = np.full((40, 40), 0.5, dtype=np.float32)
        measured = rendered + np.linspace(-0.08, 0.08, 40, dtype=np.float32)[None, :]
        result = depth_alignment(rendered, measured)
        self.assertFalse(result["accepted"])
        self.assertLess(result["depth_inlier_ratio"], 0.65)

    def test_depth_alignment_rejects_insufficient_depth(self) -> None:
        depth = np.zeros((40, 40), dtype=np.float32)
        result = depth_alignment(depth, depth)
        self.assertFalse(result["accepted"])
        self.assertEqual(0, result["depth_pixels"])


if __name__ == "__main__":
    unittest.main()
