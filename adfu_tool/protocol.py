"""BOT-style CBW/CSW framing, session transport and strict parsers.

The ADFU vendor interface (VID_10D6 & PID_10D6) speaks a BOT-flavoured
protocol: a 31-byte CBW on bulk OUT 0x01, an optional data phase in
512-byte host calls, and a 13-byte CSW on bulk IN 0x82:

    CBW: "USBC" + tag(4, zero) + dlen(4 LE) + flags(1, 0x80=IN) + LUN(1)
         + cbLen(1, 16) + CDB(16)
    CDB: opcode(1) + address(4 LE) + length(4 LE) + zero padding
    CSW: "USBS" + tag(4) + residue(4) + status(1)

Every observed success CSW is exactly ``"USBS" + nine zero bytes``. This
implementation is deliberately strict and retries nothing: a short OUT, a
non-zero CSW field, malformed or unexpected IN data all abort the session
immediately. The physical device recovers with a unplug/power-cycle, which
is the vendor's normal recovery path.
"""
import struct
import time

VID = 0x10D6
PID_NORMAL = 0x1101          # normal UDISK mass-storage mode
PID_ADFU = 0x10D6            # ADFU download mode

BULK_OUT = 0x01
BULK_IN = 0x82
MAX_PACKET = 512

LOAD_ADDRESS = 0xB4061000    # proven SRAM placement for the 2 KiB reader image
ENTRY_ADDRESS = 0xB4061000
UPLOAD_OPCODE = 0x05
EXECUTE_OPCODE = 0x10

SUCCESS_CSW = b"USBS" + bytes(9)
GETINFO_CBW = bytes.fromhex("555342430000000012000000800010cc"
                            "000000000000120000000000000000")
GETINFO_IDENTITY = bytes.fromhex("004341444655445009460000000000000000")

LOADER_IDENTITY = bytes.fromhex(          # reader loader identity32 (32 bytes):
    "5631303052393031f8a61d5981465b45"    # "V100R901" + build id + 16-byte cookie
    "397ecbe0cd4a0503ba77e8f16513f864")
LOADER_IDENTITY_PREFIX = b"V100R901"      # first eight bytes, for display
CPU_RESPONSE = 64                       # identity32 + 8 CPU words
CHUNK_FRAME = 80                        # identity32 + seq/guard/address/length + 32 data
CHUNK_DATA = 32
GUARD_OK = 1

OPERATION_TIMEOUT_S = 2.0
DEFAULT_OVERALL_TIMEOUT_S = 120.0


class AdfuError(Exception):
    """Any protocol violation or device-side refusal. Never retried."""


def build_cbw(opcode: int, address: int, length: int) -> bytes:
    """31-byte CBW with a 16-byte CDB carrying LE32 address and length."""
    cdb = bytes([opcode]) + struct.pack("<III", address, length, 0) + bytes(3)
    return b"USBC" + struct.pack("<II", 0, length) + bytes([0, 0, 16]) + cdb


def parse_csw(data: bytes):
    """Strict success CSW; returns (tag, residue, status) or raises."""
    if len(data) != 13:
        raise AdfuError(f"CSW must be 13 bytes, got {len(data)}")
    if data[:4] != b"USBS":
        raise AdfuError("CSW signature missing")
    tag, residue, status = struct.unpack("<IIB", data[4:])
    if tag != 0 or residue != 0 or status != 0:
        raise AdfuError(f"CSW rejected: tag={tag} residue={residue} status={status}")
    return tag, residue, status


class Session:
    """Bounded, journaling exchange session over a device-like object.

    The device object must provide ``write(data) -> bytes_written`` and
    ``read() -> bytes`` (one bulk-IN transfer, up to 512 bytes). A pyusb
    device wrapped by :mod:`adfu_tool.device` fits; tests substitute fakes.
    """

    def __init__(self, device, record=None, clock=time.monotonic,
                 overall_timeout: float = DEFAULT_OVERALL_TIMEOUT_S,
                 operation_timeout: float = OPERATION_TIMEOUT_S):
        self.device = device
        self.record = record or (lambda kind, value: None)
        self.clock = clock
        self.deadline = clock() + overall_timeout
        self.operation_timeout = operation_timeout

    def _timeout_ms(self) -> int:
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            raise AdfuError("overall session deadline expired")
        return int(min(self.operation_timeout, remaining) * 1000)

    def write(self, data: bytes) -> int:
        timeout = self._timeout_ms()
        self.record("out_attempt", {"hex": data.hex(), "timeout_ms": timeout})
        count = self.device.write(data, timeout)
        self.record("out_complete", {"bytes": count})
        if count != len(data):
            raise AdfuError("short OUT write; do not resend")
        return count

    def read(self) -> bytes:
        timeout = self._timeout_ms()
        self.record("in_attempt", {"timeout_ms": timeout})
        data = self.device.read(timeout)
        self.record("in_complete", {"hex": data.hex(), "bytes": len(data)})
        if not data:
            raise AdfuError("empty IN response")
        return data

    def read_exact(self, size: int, limit: int) -> bytes:
        """Assemble a bounded IN response from partial bulk transfers."""
        data = bytearray()
        for _ in range(limit):
            data.extend(self.read())
            if len(data) == size:
                return bytes(data)
            if len(data) > size:
                raise AdfuError("unexpected trailing IN bytes")
        raise AdfuError("incomplete IN response")

    def getinfo(self, expected=GETINFO_IDENTITY) -> bytes:
        """One recorded GetInfo; returns the 18-byte identity.

        Verifies against the reference bootROM stamp unless ``expected`` is
        None (the ``--identity-force`` escape hatch).
        """
        self.write(GETINFO_CBW)
        data = self.read_exact(len(GETINFO_IDENTITY), 4)
        parse_csw(self.read_exact(13, 4))
        if expected is not None and data != expected:
            raise AdfuError(f"GetInfo identity differs: {data.hex()}")
        return data

    def upload(self, encoded: bytes, address: int = LOAD_ADDRESS) -> None:
        """Send a codec-encoded image; requires the success CSW."""
        if len(encoded) % 512 or not 512 <= len(encoded) <= 65536:
            raise AdfuError("image must be 512..65536 bytes in 512-byte steps")
        self.write(build_cbw(UPLOAD_OPCODE, address, len(encoded)))
        for offset in range(0, len(encoded), MAX_PACKET):
            self.write(encoded[offset:offset + MAX_PACKET])
        parse_csw(self.read_exact(13, 4))

    def execute(self, entry: int = ENTRY_ADDRESS) -> None:
        """Request execution at ``entry``. The reply arrives as IN data."""
        self.write(build_cbw(EXECUTE_OPCODE, entry, 0))


def read_execute_response(session: Session, header: bytes, size: int):
    """Read an execute-stage IN response, optionally preceded by one CSW.

    Returns ``(data, ordering)`` where ordering is ``response_only`` or
    ``success_csw_then_response``. Anything else is rejected without
    resynchronization.
    """
    data = bytearray()
    csw_prefix = SUCCESS_CSW + header  # validates the optional leading CSW exactly
    for _ in range(size + 13):
        data.extend(session.read())
        plain = len(data) <= size and header.startswith(data[:min(len(data), len(header))])
        prefixed = len(data) <= 13 + size and \
            csw_prefix.startswith(data[:min(len(data), len(csw_prefix))])
        if plain and len(data) == size:
            return bytes(data), "response_only"
        if prefixed and len(data) == 13 + size:
            parse_csw(bytes(data[:13]))
            return bytes(data[13:]), "success_csw_then_response"
        if not plain and not prefixed:
            raise AdfuError("invalid execute reply; no resynchronization")
    raise AdfuError("incomplete execute reply")
