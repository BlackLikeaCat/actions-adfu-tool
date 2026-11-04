"""Vendor ADFU image codec: 256-byte XOR key plus a 12-byte block permutation.

Derived from ``meta/actions/encrypt.c`` in the gipi/teardown repository, itself
attributed to Amaury Pouly / Rockbox (GPL-2.0-or-later). The key table below is
the public constant from that file. This module is therefore distributed under
GPL-2.0-or-later as well.

The implementation was verified against the reference C code during the
memory-book investigation: all 65,536 byte/key combinations, 24 synthetic
patterns, and the real vendor firmware artifact round-trip identically.

Images must be non-empty multiples of 512 bytes. Encoding is applied to the
whole image at once (never per 512-byte host call).
"""

KEY = bytes.fromhex(
    "00e9692e2b131332abc0696069eddf6079647505ec089b6d9c1f19649a5566a879"
    "7f9a2947935074ed9a7d07fd60e7dbd0d461d4e9123d9ad1005b07fc36beea00"
    "e48e81b56f81b46d1c1f7585c0b460129f16c7e9133a0c61301f40a3933d691c"
    "b04a8afc325a47d1cc00378a99334d11c8543b07125ba2d48cfdd2f39a3fd578"
    "e7ea36e91cd483188c800ced339a1904df375a694fd51ca029c7bcb41f47dff2"
    "75fab7d463b83f301807726dffc14bc8fd185b5b8007de812cd4576139783348"
    "5d85ad045c331f7f3874fa60df13b4a3d2796e9fcedb607966ddc3189a7255b8"
    "79dd79373a398118a8694c1c121ff06de7dd1318fa3238618a3a95c41268c3"
)

# Known-input test vector (512 bytes of 0x00..0xff twice, first 32 shown).
VECTOR_PLAIN = bytes(range(256)) * 2
VECTOR_ENCODED_PREFIX = bytes.fromhex("012c0204002d032e08a2a1a0646a67100c6b666814f9fafb8585861c18848787")


def _apply(data: bytes, decode: bool) -> bytes:
    if not data or len(data) % 512:
        raise ValueError("codec needs a non-empty, 512-byte aligned image")
    result = bytearray(data)
    order = (4, 0, 2, 6, 3, 7, 5, 1) if decode else (1, 7, 2, 4, 0, 6, 3, 5)

    def permute():
        # Preserve the reference's strict i+12<length boundary, including tail.
        for i in range(0, len(result) - 12, 12):
            block = result[i:i + 8]
            result[i:i + 8] = bytes(block[j] for j in order)

    def xor():
        for i in range(0, len(result), 4):
            value = KEY[result[i]]
            for j in (1, 2, 3):
                result[i + j] ^= value

    if decode:
        permute()
        xor()
    else:
        xor()
        permute()
    return bytes(result)


def encode(data: bytes) -> bytes:
    """Host-to-device image encoding."""
    return _apply(data, decode=False)


def decode(data: bytes) -> bytes:
    """Device-to-host image decoding."""
    return _apply(data, decode=True)
