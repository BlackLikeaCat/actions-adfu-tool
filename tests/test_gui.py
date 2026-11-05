"""GUI structural tests: no window creation, pure logic only."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adfu_tool import __version__, gui
from adfu_tool.loader import Window


class GuiStructureTests(unittest.TestCase):
    def test_module_exposes_app_and_runner(self):
        self.assertTrue(hasattr(gui, "GuiApp"))
        self.assertTrue(callable(gui.run))
        self.assertEqual(gui.PROJECT_URL, "https://github.com/BlackLikeaCat/actions-adfu-tool")

    def test_import_does_not_create_windows(self):
        # Importing the module must not touch Tk; __init__ is the only
        # place that builds widgets.
        self.assertIsNone(gui.GuiApp.__dict__.get("root"))

    def test_timestamp_shape(self):
        value = gui.timestamp()
        self.assertRegex(value, r"^\d{2}:\d{2}:\d{2}$")


class GuiPolicyTests(unittest.TestCase):
    """The GUI must stay inside the CLI's safety envelope."""

    def test_window_validation_shared_with_cli(self):
        from adfu_tool.protocol import AdfuError
        with self.assertRaises(AdfuError):
            gui.loader_mod.validate_window(Window(0xBFC00800, 1024))
        gui.loader_mod.validate_window(Window(0xBFC10000, 512))

    def test_default_dump_uses_sealed_image(self):
        plain, encoded = gui.loader_mod.image_for_window(gui.loader_mod.DEFAULT_WINDOW)
        self.assertEqual(gui.loader_mod.sha256(encoded),
                         gui.loader_mod.SEALED_ENCODED_SHA256)

    def test_version_matches_package(self):
        import re
        source = (Path(gui.__file__).parent / "__init__.py").read_text()
        self.assertIn(f'__version__ = "{__version__}"', source)


if __name__ == "__main__":
    unittest.main()
