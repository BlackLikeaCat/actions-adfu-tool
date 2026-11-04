"""Loader image integrity and window repatching tests."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adfu_tool import codec, loader
from adfu_tool.loader import (DEFAULT_WINDOW, PERPASS_ORI, START_LUI, TOTAL_ORI,
                              Window)
from adfu_tool.protocol import AdfuError


class SealedImageTests(unittest.TestCase):
    def test_sealed_hashes(self):
        plain, encoded = loader.load_default()
        self.assertEqual(loader.sha256(plain), loader.SEALED_PLAINTEXT_SHA256)
        self.assertEqual(loader.sha256(encoded), loader.SEALED_ENCODED_SHA256)
        self.assertEqual(len(plain), 2048)

    def test_codec_roundtrip_of_sealed_image(self):
        plain, encoded = loader.load_default()
        self.assertEqual(codec.decode(encoded), plain)

    def test_skeleton_site_counts(self):
        plain, _ = loader.load_default()
        for pattern, expected in ((START_LUI, 2), (TOTAL_ORI, 1), (PERPASS_ORI, 1)):
            sites = [i for i in range(len(plain) - 3) if plain[i:i + 4] == pattern]
            self.assertEqual(len(sites), expected, pattern.hex())

    def test_provenance_json(self):
        info = loader.provenance()
        self.assertEqual(info["identity"], "V100R901")
        self.assertEqual(info["plaintext"]["sha256"], loader.SEALED_PLAINTEXT_SHA256)


class WindowTests(unittest.TestCase):
    def test_default_window_returns_sealed_bytes(self):
        plain, encoded = loader.image_for_window(DEFAULT_WINDOW)
        sealed_plain, sealed_encoded = loader.load_default()
        self.assertEqual(plain, sealed_plain)
        self.assertEqual(encoded, sealed_encoded)

    def _sites(self, image, word):
        pattern = word.to_bytes(4, "little")
        return [i for i in range(len(image) - 3) if image[i:i + 4] == pattern]

    def test_patched_window_only_changes_immediates(self):
        plain, _ = loader.load_default()
        window = Window(0xBFC10000, 16)
        patched, encoded = loader.image_for_window(window)
        diffs = [i for i in range(2048) if patched[i] != plain[i]]
        self.assertTrue(0 < len(diffs) <= 16)
        # Patch by pre-scanned offsets: the sites that held the original
        # start/count words now hold the window's values.
        start_sites = self._sites(plain, 0x3C050000 | 0xBFC0)
        total_site = self._sites(plain, 0x340E0000 | 2048)[0]
        perpass_site = self._sites(plain, 0x340E0000 | 1024)[0]
        self.assertEqual(len(start_sites), 2)
        for site in start_sites:
            self.assertEqual(int.from_bytes(patched[site:site + 4], "little"),
                             0x3C050000 | 0xBFC1)
        self.assertEqual(int.from_bytes(patched[total_site:total_site + 4], "little"),
                         0x340E0000 | 32)
        self.assertEqual(int.from_bytes(patched[perpass_site:perpass_site + 4], "little"),
                         0x340E0000 | 16)
        self.assertEqual(codec.decode(encoded), patched)

    def test_half_window_words_are_independent(self):
        # cpp=512 patches the total word (1024) onto the value the sealed image
        # used for its per-pass constant; offset-based patching must keep the
        # two sites independent.
        window = Window(0xBFC00000, 512)
        patched, encoded = loader.image_for_window(window)
        plain, _ = loader.load_default()
        for site in self._sites(plain, 0x340E0000 | 2048):
            self.assertEqual(int.from_bytes(patched[site:site + 4], "little"),
                             0x340E0000 | 1024)
        for site in self._sites(plain, 0x340E0000 | 1024):
            self.assertEqual(int.from_bytes(patched[site:site + 4], "little"),
                             0x340E0000 | 512)
        self.assertEqual(codec.decode(encoded), patched)

    def test_misaligned_start_refused(self):
        with self.assertRaises(AdfuError):
            loader.image_for_window(Window(0xBFC00800, 1024))

    def test_out_of_range_chunk_counts_refused(self):
        for count in (0, 1025, -1):
            with self.subTest(count=count), self.assertRaises(AdfuError):
                loader.image_for_window(Window(0xBFC00000, count))

    def test_extra_passes_refused(self):
        with self.assertRaises(AdfuError):
            loader.image_for_window(Window(0xBFC00000, 1024, passes=3))

    def test_damaged_skeleton_refused(self):
        plain, _ = loader.load_default()
        damaged = bytearray(plain)
        first = plain.find(START_LUI)
        damaged[first:first + 4] = b"\x00\x00\x00\x00"
        try:
            loader._patch(bytes(damaged), Window(0xBFC10000, 16))
        except AdfuError as error:
            self.assertIn("skeleton mismatch", str(error))
        else:
            self.fail("damaged skeleton accepted")


if __name__ == "__main__":
    unittest.main()
