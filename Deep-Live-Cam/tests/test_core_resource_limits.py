import platform
import unittest

import modules.core as core
import modules.globals


@unittest.skipUnless(platform.system().lower() == "darwin", "macOS-only resource limit behavior")
class MacOSResourceLimitTests(unittest.TestCase):
    def tearDown(self):
        modules.globals.max_memory = None

    def test_suggest_max_memory_defaults_to_24_gb_on_macos(self):
        self.assertEqual(core.suggest_max_memory(), 24)

    def test_limit_resources_accepts_24_gb_on_macos(self):
        modules.globals.max_memory = 24

        core.limit_resources()


if __name__ == "__main__":
    unittest.main()
