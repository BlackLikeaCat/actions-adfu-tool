"""Reader-loader stream: CPU response, 80-byte chunk frames, two-pass assembly."""
import struct
import time

from .loader import Window
from .protocol import (CHUNK_DATA, CHUNK_FRAME, CPU_RESPONSE, GUARD_OK,
                       LOADER_IDENTITY, AdfuError, Session, SUCCESS_CSW,
                       read_execute_response)

# CPU words observed on the reference V100 card (PRId, Config0..3, validity).
# A mismatch is reported as a warning, not an error: other family chips differ.
KNOWN_CPU_WORDS = (0x19655, 0x80A40483, 0xBE63319E, 0x80000000, 0x2420, 31)


def parse_cpu(data: bytes, header: bytes) -> dict:
    if len(data) != CPU_RESPONSE or data[:32] != header:
        raise AdfuError("CPU response size or build identity differs")
    words = struct.unpack("<8I", data[32:])
    known = words[:6] == KNOWN_CPU_WORDS
    return {
        "prid": f"{words[0]:08x}", "config0": f"{words[1]:08x}",
        "config1": f"{words[2]:08x}", "config2": f"{words[3]:08x}",
        "config3": f"{words[4]:08x}", "validity_flags": f"{words[5]:08x}",
        "entry_status": f"{words[6]:08x}", "entry_sp": f"{words[7]:08x}",
        "matches_reference_v100": known,
    }


def parse_chunk(data: bytes, header: bytes, sequence: int, window: Window) -> dict:
    if not 1 <= sequence <= window.total_chunks:
        raise AdfuError("chunk sequence outside the requested window")
    if len(data) != CHUNK_FRAME or data[:32] != header:
        raise AdfuError("chunk size or build identity differs")
    seq, guard, address, length = struct.unpack("<4I", data[32:48])
    if seq != sequence:
        raise AdfuError(f"chunk sequence violation: got {seq}, expected {sequence}")
    if guard != GUARD_OK:
        raise AdfuError("loader SRAM guards failed; refusing to trust chunk data")
    offset = ((sequence - 1) % window.chunks_per_pass) * CHUNK_DATA
    if address != window.start + offset or length != CHUNK_DATA:
        raise AdfuError(f"chunk address/length differs: {address:08x}/{length}")
    return {
        "sequence": seq, "pass_number": 1 + (seq - 1) // window.chunks_per_pass,
        "offset": offset, "address": f"{address:08x}", "bytes": length,
        "data_hex": data[48:].hex(),
    }


def assemble(chunks: list, window: Window) -> bytes:
    """Assemble pass 1 and pass 2; both must be complete and identical."""
    if len(chunks) != window.total_chunks:
        raise AdfuError(f"incomplete stream: {len(chunks)}/{window.total_chunks} chunks")
    passes = [bytearray(), bytearray()]
    for seq, chunk in enumerate(chunks, 1):
        number = 1 + (seq - 1) // window.chunks_per_pass
        offset = ((seq - 1) % window.chunks_per_pass) * CHUNK_DATA
        if chunk["pass_number"] != number or chunk["offset"] != offset:
            raise AdfuError("chunk order violates pass layout")
        value = bytes.fromhex(chunk["data_hex"])
        if len(value) != CHUNK_DATA:
            raise AdfuError("chunk data size differs")
        passes[number - 1].extend(value)
    if passes[0] != passes[1]:
        raise AdfuError("pass 2 data differs from pass 1")
    return bytes(passes[0])


def run_read(session: Session, encoded_image: bytes, window: Window,
             on_progress=None, header: bytes = LOADER_IDENTITY):
    """Full proven sequence: upload, execute, CPU response, chunk stream.

    Returns ``(rom_bytes, info_dict)``. ``rom_bytes`` is only produced after
    both passes arrived and matched. No command is ever retried; on any error
    the caller should stop talking to the device and power-cycle it.
    """
    if len(header) != 32 or not header.startswith(b"V100"):
        raise AdfuError("loader identity must be 32 bytes starting with V100")

    session.upload(encoded_image)
    session.execute()
    raw, ordering = read_execute_response(session, header, CPU_RESPONSE)
    cpu = parse_cpu(raw, header)
    if on_progress:
        on_progress("cpu", 0, window.total_chunks, ordering=ordering, cpu=cpu)

    chunks = []
    for sequence in range(1, window.total_chunks + 1):
        frame = session.read_exact(CHUNK_FRAME, CHUNK_FRAME)
        chunk = parse_chunk(frame, header, sequence, window)
        if sequence > window.chunks_per_pass and \
                chunk["data_hex"] != chunks[sequence - window.chunks_per_pass - 1]["data_hex"]:
            raise AdfuError(f"pass 2 differs from pass 1 at offset {chunk['offset']:x}")
        chunks.append(chunk)
        if on_progress:
            on_progress("chunk", sequence, window.total_chunks, chunk=chunk)

    rom = assemble(chunks, window)
    info = {
        "ordering": ordering,
        "cpu": cpu,
        "window": {"start": f"{window.start:08x}", "bytes": window.window_bytes,
                   "chunks_per_pass": window.chunks_per_pass, "passes": window.passes},
        "passes_match": True,
        "chunks_received": len(chunks),
    }
    return rom, info


def frame_bytes(header: bytes, sequence: int, address: int, data: bytes) -> bytes:
    """Build one 80-byte frame (used by tests and by loader authors)."""
    return header + struct.pack("<4I", sequence, GUARD_OK, address, CHUNK_DATA) + data


def success_csw() -> bytes:
    return SUCCESS_CSW
