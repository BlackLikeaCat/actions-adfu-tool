"""CLI surface tests (offline commands only; no device required)."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adfu_tool import __version__, cli
from adfu_tool.protocol import AdfuError


class CliTests(unittest.TestCase):
    def test_version_flag(self):
        with patch("sys.argv", ["adfu-tool", "--version"]), \
             patch("sys.stdout"):
            with self.assertRaises(SystemExit) as done:
                cli.main()
        self.assertEqual(done.exception.code, 0)

    def test_no_command_prints_help(self):
        with patch("sys.argv", ["adfu-tool"]), patch("sys.stdout"):
            self.assertEqual(cli.main(), 0)

    def test_window_parsing(self):
        window = cli._parse_window("0xBFC08000:512")
        self.assertEqual(window.start, 0xBFC08000)
        self.assertEqual(window.chunks_per_pass, 512)
        with self.assertRaises(AdfuError):
            cli._parse_window("nonsense")

    def test_dump_rom_window_guard(self):
        from types import SimpleNamespace as S
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            args = S(output=Path(tmp) / "rom.bin", window="0xBFC10000:512",
                     allow_experimental_window=False, force=True, raw_loader=None,
                     raw=False, identity_force=False, no_journal=True)
            with self.assertRaisesRegex(AdfuError, "experimental"):
                cli._dump_rom(args)
            args.allow_experimental_window = True
            with patch("adfu_tool.device.open_single_adfu",
                       side_effect=AdfuError("no device here")), patch("sys.stderr"):
                with self.assertRaisesRegex(AdfuError, "no device here"):
                    cli._dump_rom(args)

    def test_errors_are_reported_not_raised(self):
        with patch("sys.argv", ["adfu-tool", "info"]), \
             patch("adfu_tool.device.open_single_adfu",
                   side_effect=AdfuError("expected exactly one ADFU device")), \
             patch("sys.stderr"):
            self.assertEqual(cli.main(), 2)

    def test_upload_requires_yes(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "loader.bin"
            image.write_bytes(bytes(2048))
            with patch("sys.argv", ["adfu-tool", "upload", "--file", str(image)]), \
                 patch("sys.stderr"):
                self.assertEqual(cli.main(), 2)


if __name__ == "__main__":
    unittest.main()
