import unittest

import modules.core as core


class MediaResourceLimitTests(unittest.TestCase):
    def test_default_video_resource_limits_accept_normal_media(self):
        core.assert_video_resource_limits(width=1920, height=1080, frame_count=300)

    def test_default_video_resource_limits_reject_excessive_pixel_count(self):
        with self.assertRaises(ValueError):
            core.assert_video_resource_limits(width=20000, height=12000, frame_count=1)

    def test_default_video_resource_limits_reject_excessive_frame_count(self):
        with self.assertRaises(ValueError):
            core.assert_video_resource_limits(width=1920, height=1080, frame_count=200000)


if __name__ == "__main__":
    unittest.main()
