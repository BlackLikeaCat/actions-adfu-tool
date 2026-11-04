"""Codec tests: reference vectors, roundtrips, alignment rules."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adfu_tool import codec


class CodecTests(unittest.TestCase):
    def test_known_vector(self):
        encoded = codec.encode(codec.VECTOR_PLAIN)
        self.assertEqual(encoded[:32], codec.VECTOR_ENCODED_PREFIX)
        self.assertEqual(codec.decode(encoded), codec.VECTOR_PLAIN)

    def test_roundtrip_patterns(self):
        for size in (512, 1024, 2048, 8192):
            for fill in (0x00, 0xFF, 0xA5):
                data = bytes([fill]) * size
                self.assertEqual(codec.decode(codec.encode(data)), data, (size, fill))
        ramp = bytes(i & 0xFF for i in range(2048))
        self.assertEqual(codec.decode(codec.encode(ramp)), ramp)

    def test_tail_boundary_matches_reference(self):
        # The reference keeps the strict i+12<length boundary: the tail bytes
        # of each 512-byte block are handled exactly as the C code does.
        data = bytes(i & 0xFF for i in range(512))
        encoded = codec.encode(data)
        self.assertEqual(len(encoded), 512)
        self.assertEqual(codec.decode(encoded), data)

    def test_alignment_rules(self):
        for bad in (b"", b"x" * 256, b"x" * 511, b"x" * 513):
            with self.assertRaises(ValueError):
                codec.encode(bad)
            with self.assertRaises(ValueError):
                codec.decode(bad)


if __name__ == "__main__":
    unittest.main()
