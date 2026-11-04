"""Shared fake-endpoint helpers for adfu-tool tests (offline only)."""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adfu_tool.loader import Window
from adfu_tool.protocol import CHUNK_DATA, LOADER_IDENTITY
from adfu_tool.reader import frame_bytes

HEADER = LOADER_IDENTITY  # 32-byte identity32: "V100R901" + build id + cookie


def cpu_response(header=HEADER, prid=0x19655, status=0, sp=0xDEADBEEF):
    """64-byte execute-stage response: identity32 + eight CPU words."""
    words = (prid, 0x80A40483, 0xBE63319E, 0x80000000, 0x2420, 31, status, sp)
    return header + struct.pack("<8I", *words)


def csw(tag=0, residue=0, status=0):
    return struct.pack("<4sIIB", b"USBS", tag, residue, status)


class FakeDevice:
    """Scripted bulk endpoints: responses are consumed by read; failures by index."""

    def __init__(self, responses, fail_at=0, short_at=0):
        self.responses = list(responses)
        self.fail_at = fail_at
        self.short_at = short_at
        self.calls = []
        self.writes = []

    def _call(self, kind):
        self.calls.append(kind)
        if len(self.calls) == self.fail_at:
            raise TimeoutError("simulated disconnect")

    def write(self, data, timeout_ms):
        self._call("out")
        self.writes.append(bytes(data))
        assert 0 < timeout_ms <= 2000
        return len(data) - (1 if len(self.calls) == self.short_at else 0)

    def read(self, timeout_ms):
        self._call("in")
        assert 0 < timeout_ms <= 2000
        return self.responses.pop(0)


def make_frames(window: Window, contents: bytes, header=HEADER):
    """All frames for one full two-pass read of ``window`` over ``contents``."""
    frames = []
    for seq in range(1, window.total_chunks + 1):
        offset = ((seq - 1) % window.chunks_per_pass) * CHUNK_DATA
        frames.append(frame_bytes(header, seq, window.start + offset,
                                  contents[offset:offset + CHUNK_DATA]))
    return frames


def full_stream(window: Window, contents: bytes, execute_csw=False, header=HEADER):
    """IN responses of a complete successful session: upload CSW, then the
    execute-stage CPU response (optionally CSW-prefixed), then all frames."""
    cpu = cpu_response(header)
    return [csw(), (csw() + cpu) if execute_csw else cpu] + \
        make_frames(window, contents, header)


def synthetic_contents(window: Window):
    size = window.window_bytes
    return bytes((i * 73 + (i >> 3) * 19 + 11) & 0xFF for i in range(size))
