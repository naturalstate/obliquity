"""Generate hash fixtures for testing the Obliquity `crack` pillar.

Writes hash files (one per algorithm) plus an answer key, into testlab/fixtures/.
Some plaintexts are in rockyou / the bundled lists (crackable), some are random
(won't crack) so you can verify the tool reports partial success correctly.

    python -m testlab.hashes           # writes testlab/fixtures/*
"""

from __future__ import annotations

import hashlib
import secrets
from pathlib import Path

# hashcat -m modes for each file we emit
MODES = {"md5": 0, "sha1": 100, "sha256": 1400, "ntlm": 1000}

# crackable plaintexts (present in rockyou / bundled passwords-common.txt)
CRACKABLE = ["password123", "letmein", "iloveyou", "admin", "toor", "qwerty", "hunter2"]
# random 16-hex plaintexts that won't be in any wordlist
UNCRACKABLE = [secrets.token_hex(8) for _ in range(3)]


def _md4(data: bytes) -> bytes:
    """Pure-Python MD4 (Python 3.13+ dropped it from hashlib) -- needed for NTLM."""
    def lrot(x, n):
        x &= 0xFFFFFFFF
        return ((x << n) | (x >> (32 - n))) & 0xFFFFFFFF

    msg = bytearray(data)
    orig_bits = (8 * len(data)) & 0xFFFFFFFFFFFFFFFF
    msg.append(0x80)
    while len(msg) % 64 != 56:
        msg.append(0)
    msg += orig_bits.to_bytes(8, "little")

    a, b, c, d = 0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476
    for off in range(0, len(msg), 64):
        x = [int.from_bytes(msg[off + i:off + i + 4], "little") for i in range(0, 64, 4)]
        aa, bb, cc, dd = a, b, c, d

        def f(x, y, z): return (x & y) | (~x & z)
        def g(x, y, z): return (x & y) | (x & z) | (y & z)
        def h(x, y, z): return x ^ y ^ z

        for i in range(4):
            k = i * 4
            a = lrot(a + f(b, c, d) + x[k], 3);   d = lrot(d + f(a, b, c) + x[k + 1], 7)
            c = lrot(c + f(d, a, b) + x[k + 2], 11); b = lrot(b + f(c, d, a) + x[k + 3], 19)
        for i in range(4):
            a = lrot(a + g(b, c, d) + x[i] + 0x5A827999, 3)
            d = lrot(d + g(a, b, c) + x[i + 4] + 0x5A827999, 5)
            c = lrot(c + g(d, a, b) + x[i + 8] + 0x5A827999, 9)
            b = lrot(b + g(c, d, a) + x[i + 12] + 0x5A827999, 13)
        order = [0, 8, 4, 12, 2, 10, 6, 14, 1, 9, 5, 13, 3, 11, 7, 15]
        for i in range(0, 16, 4):
            a = lrot(a + h(b, c, d) + x[order[i]] + 0x6ED9EBA1, 3)
            d = lrot(d + h(a, b, c) + x[order[i + 1]] + 0x6ED9EBA1, 9)
            c = lrot(c + h(d, a, b) + x[order[i + 2]] + 0x6ED9EBA1, 11)
            b = lrot(b + h(c, d, a) + x[order[i + 3]] + 0x6ED9EBA1, 15)
        a = (a + aa) & 0xFFFFFFFF; b = (b + bb) & 0xFFFFFFFF
        c = (c + cc) & 0xFFFFFFFF; d = (d + dd) & 0xFFFFFFFF
    return b"".join(v.to_bytes(4, "little") for v in (a, b, c, d))


def _hash(algo: str, pw: str) -> str:
    if algo == "md5":
        return hashlib.md5(pw.encode()).hexdigest()
    if algo == "sha1":
        return hashlib.sha1(pw.encode()).hexdigest()
    if algo == "sha256":
        return hashlib.sha256(pw.encode()).hexdigest()
    if algo == "ntlm":
        return _md4(pw.encode("utf-16le")).hex()
    raise ValueError(algo)


def main() -> None:
    out = Path(__file__).resolve().parent / "fixtures"
    out.mkdir(exist_ok=True)
    plaintexts = CRACKABLE + UNCRACKABLE
    answer_lines = ["# hash : plaintext  (crackable ones are common passwords)"]
    for algo, mode in MODES.items():
        lines = []
        for pw in plaintexts:
            h = _hash(algo, pw)
            lines.append(h)
            answer_lines.append(f"{algo} -m {mode}  {h} : {pw}")
        path = out / f"hashes-{algo}.txt"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {path}  (-m {mode}, {len(lines)} hashes)")
    (out / "answers.txt").write_text("\n".join(answer_lines) + "\n", encoding="utf-8")
    print(f"wrote {out / 'answers.txt'}  (the answer key)")
    print(f"\n{len(CRACKABLE)} of {len(plaintexts)} per file are crackable "
          f"(rockyou / bundled lists); {len(UNCRACKABLE)} are random and won't crack.")


if __name__ == "__main__":
    main()
