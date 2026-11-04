"""Reader stream tests against fake endpoints with the real loader image."""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adfu_tool import loader
from adfu_tool.loader import Window
from adfu_tool.protocol import AdfuError, Session
from adfu_tool.reader import assemble, parse_chunk, parse_cpu, run_read
from helpers import (FakeDevice, HEADER, csw, cpu_response, full_stream,
                     make_frames, synthetic_contents)

WINDOW = Window(0xBFC00000, 8)          # small window: 8 chunks/pass, 16 total
CONTENTS = synthetic_contents(WINDOW)
PLAIN, ENCODED = loader.image_for_window(WINDOW)


class RunReadTests(unittest.TestCase):
    def test_two_passes_match_and_assemble(self):
        device = FakeDevice(full_stream(WINDOW, CONTENTS))
        rom, info = run_read(Session(device), ENCODED, WINDOW)
        self.assertEqual(rom, CONTENTS)
        self.assertEqual(info["ordering"], "response_only")
        self.assertEqual(info["chunks_received"], WINDOW.total_chunks)
        self.assertTrue(info["passes_match"])
        self.assertTrue(info["cpu"]["matches_reference_v100"])
        # upload = CBW + 4 data writes, then the upload CSW read, then the
        # execute CBW, then CPU + frames
        self.assertEqual(len(device.writes), 6)
        reads = 1 + WINDOW.total_chunks  # CPU, then frames (upload CSW counted below)
        self.assertEqual(device.calls,
                         ["out"] * 5 + ["in"] + ["out"] + ["in"] * reads)

    def test_csw_then_response_ordering(self):
        device = FakeDevice(full_stream(WINDOW, CONTENTS, execute_csw=True))
        rom, info = run_read(Session(device), ENCODED, WINDOW)
        self.assertEqual(info["ordering"], "success_csw_then_response")
        self.assertEqual(rom, CONTENTS)

    def test_all_split_points(self):
        responses = full_stream(WINDOW, CONTENTS)
        for split in (1, 33, 63):
            device = FakeDevice([responses[0], responses[1][:split], responses[1][split:]]
                                + responses[2:])
            rom, _ = run_read(Session(device), ENCODED, WINDOW)
            self.assertEqual(rom, CONTENTS)

    def test_pass2_mismatch_detected(self):
        responses = full_stream(WINDOW, CONTENTS)
        responses[-1] = responses[-1][:48] + bytes(32)
        device = FakeDevice(responses)
        with self.assertRaisesRegex(AdfuError, "pass 2 differs"):
            run_read(Session(device), ENCODED, WINDOW)

    def test_upload_failure_prevents_execute(self):
        device = FakeDevice([csw(tag=1)])
        with self.assertRaises(AdfuError):
            run_read(Session(device), ENCODED, WINDOW)
        self.assertEqual(len(device.writes), 5)  # CBW + 4 data, no execute

    def test_execute_stage_never_starts_stream_on_bad_cpu(self):
        device = FakeDevice([csw(), b"V100XXXX" + bytes(24) + bytes(32)])
        with self.assertRaises(AdfuError):
            run_read(Session(device), ENCODED, WINDOW)

    def test_guard_failure_aborts(self):
        bad = HEADER + struct.pack("<4I", 1, 0, WINDOW.start, 32) + bytes(32)
        device = FakeDevice([csw(), cpu_response(), bad])
        with self.assertRaisesRegex(AdfuError, "guards"):
            run_read(Session(device), ENCODED, WINDOW)

    def test_sequence_violation_aborts(self):
        wrong = HEADER + struct.pack("<4I", 2, 1, WINDOW.start, 32) + bytes(32)
        device = FakeDevice([csw(), cpu_response(), wrong])
        with self.assertRaisesRegex(AdfuError, "sequence violation"):
            run_read(Session(device), ENCODED, WINDOW)

    def test_wrong_chunk_address_aborts(self):
        wrong = HEADER + struct.pack("<4I", 1, 1, WINDOW.start + 0x10000, 32) + bytes(32)
        device = FakeDevice([csw(), cpu_response(), wrong])
        with self.assertRaisesRegex(AdfuError, "address/length"):
            run_read(Session(device), ENCODED, WINDOW)

    def test_coalesced_frames_rejected(self):
        responses = full_stream(WINDOW, CONTENTS)
        frames = responses[2:]
        device = FakeDevice(responses[:2] + [frames[0] + frames[1]] + frames[2:])
        with self.assertRaisesRegex(AdfuError, "trailing"):
            run_read(Session(device), ENCODED, WINDOW)

    def test_disconnect_mid_stream_stops(self):
        responses = full_stream(WINDOW, CONTENTS)
        device = FakeDevice(responses[:6], fail_at=8)
        with self.assertRaises(TimeoutError):
            run_read(Session(device), ENCODED, WINDOW)

    def test_progress_callback(self):
        events = []
        device = FakeDevice(full_stream(WINDOW, CONTENTS))
        run_read(Session(device), ENCODED, WINDOW,
                 on_progress=lambda kind, seq, total, **extra: events.append((kind, seq)))
        self.assertEqual(events[0], ("cpu", 0))
        self.assertEqual(events[-1], ("chunk", WINDOW.total_chunks))


class ParserTests(unittest.TestCase):
    def test_cpu_parse_and_warning_flag(self):
        cpu = parse_cpu(cpu_response(), HEADER)
        self.assertTrue(cpu["matches_reference_v100"])
        self.assertEqual(cpu["prid"], "00019655")
        other = parse_cpu(cpu_response(prid=0x12345), HEADER)
        self.assertFalse(other["matches_reference_v100"])

    def test_chunk_parse(self):
        chunk = parse_chunk(make_frames(WINDOW, CONTENTS)[5], HEADER, 6, WINDOW)
        self.assertEqual(chunk["sequence"], 6)
        self.assertEqual(chunk["pass_number"], 1)
        self.assertEqual(chunk["offset"], 5 * 32)
        self.assertEqual(chunk["address"], f"{WINDOW.start + 160:08x}")

    def test_wrong_size_rejected(self):
        with self.assertRaises(AdfuError):
            parse_chunk(make_frames(WINDOW, CONTENTS)[0][:79], HEADER, 1, WINDOW)

    def test_assemble_requires_complete_and_matching(self):
        chunks = [parse_chunk(f, HEADER, i + 1, WINDOW)
                  for i, f in enumerate(make_frames(WINDOW, CONTENTS))]
        self.assertEqual(assemble(chunks, WINDOW), CONTENTS)


if __name__ == "__main__":
    unittest.main()
