"""Bundled reader loader image plus experimental window repatching.

The default image is the exact 2 KiB program proven live on 2026-11-04
(experiment v100-rom32k-h9-001): it reads [BFC00000,BFC08000) twice and
streams 80-byte frames over bulk IN. Its plaintext and encoded forms are
bound by SHA-256 in ``data/rom32k_h9.provenance.json``.

For other windows the loader is repatched instead of rebuilt: the start
address and chunk counts live in four immediate-only instruction words
(``lui $a1, start_hi`` x2, ``ori $t6, total``, ``ori $t6, per_pass``).
Every other byte must match the sealed plaintext or the patch refuses.
Windows must start on a 64 KiB boundary and cover at most 32 KiB per pass.
"""
import hashlib
import json
import struct
from dataclasses import dataclass
from importlib import resources

from .codec import encode
from .protocol import AdfuError, CHUNK_DATA

SEALED_PLAINTEXT_SHA256 = "c50bd82d354152cf9d7ca81bcaee8f62018a9837e4e6fe9a0f714457f8d75c7f"
SEALED_ENCODED_SHA256 = "163f85951547759fa48d3ac431f4041dba235893bc472c75d3b23a2d6527f97f"

MAX_CHUNKS = 2048

# Instruction words inside the sealed plaintext (MIPS32 little-endian):
START_LUI = bytes.fromhex("c0bf053c")     # lui  $a1, 0xbfc0   (2 sites: init + pass reset)
TOTAL_ORI = bytes.fromhex("00080e34")     # ori  $t6, $zero, 2048
PERPASS_ORI = bytes.fromhex("00040e34")   # ori  $t6, $zero, 1024


@dataclass(frozen=True)
class Window:
    """A read window: ``start`` (64 KiB aligned) and chunks of 32 bytes per pass."""
    start: int
    chunks_per_pass: int
    passes: int = 2

    @property
    def chunk_bytes(self) -> int:
        return CHUNK_DATA

    @property
    def window_bytes(self) -> int:
        return self.chunks_per_pass * CHUNK_DATA

    @property
    def total_chunks(self) -> int:
        return self.chunks_per_pass * self.passes


DEFAULT_WINDOW = Window(0xBFC00000, 1024)


def _data_bytes(name: str) -> bytes:
    return resources.files("adfu_tool").joinpath("data", name).read_bytes()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_default():
    """Return the sealed (plaintext, encoded) loader image pair."""
    plain = _data_bytes("rom32k_h9.bin")
    encoded = _data_bytes("rom32k_h9.encoded.bin")
    if sha256(plain) != SEALED_PLAINTEXT_SHA256 or sha256(encoded) != SEALED_ENCODED_SHA256:
        raise AdfuError("bundled loader image does not match its sealed provenance")
    return plain, encoded


def _patch(plain: bytes, window: Window) -> bytes:
    total = 0x340E0000 | window.total_chunks
    per_pass = 0x340E0000 | window.chunks_per_pass
    start_lui = 0x3C050000 | ((window.start >> 16) & 0xFFFF)

    plan = []
    for pattern, word, expected in ((START_LUI, start_lui, 2),
                                    (TOTAL_ORI, total, 1),
                                    (PERPASS_ORI, per_pass, 1)):
        sites = [i for i in range(len(plain) - 3) if plain[i:i + 4] == pattern]
        if len(sites) != expected:
            raise AdfuError(
                f"loader skeleton mismatch: {pattern.hex()} found {len(sites)}x, "
                f"expected {expected}x - refusing to patch")
        plan.extend((site, word) for site in sites)
    spans = [span for site, _ in plan for span in range(site, site + 4)]
    if len(spans) != len(set(spans)):
        raise AdfuError("loader patch sites overlap - refusing")

    out = bytearray(plain)
    for site, word in plan:
        out[site:site + 4] = struct.pack("<I", word)
    return bytes(out)


def validate_window(window: Window) -> None:
    if window.start % 0x10000:
        raise AdfuError("window start must be 64 KiB aligned (loader uses lui only)")
    if not 1 <= window.chunks_per_pass <= 1024:
        raise AdfuError("window must cover 32..32768 bytes per pass (1..1024 chunks)")
    if window.passes != 2:
        raise AdfuError("the loader always performs exactly two passes")
    if window.total_chunks > MAX_CHUNKS:
        raise AdfuError("window exceeds the loader's 2048-chunk stream")


def image_for_window(window: Window):
    """(plaintext, encoded) image for ``window``; default window returns the sealed bytes."""
    validate_window(window)
    plain, encoded = load_default()
    if window == DEFAULT_WINDOW:
        return plain, encoded
    patched = _patch(plain, window)
    encoded = encode(patched)
    if decode_roundtrip(encoded, patched) is False:  # pragma: no cover - defensive
        raise AdfuError("codec roundtrip failed for patched window")
    return patched, encoded


def decode_roundtrip(encoded: bytes, plain: bytes) -> bool:
    from .codec import decode
    return decode(encoded) == plain


def provenance() -> dict:
    return json.loads(_data_bytes("rom32k_h9.provenance.json"))
