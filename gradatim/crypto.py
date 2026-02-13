"""
Cryptographic primitives for the agent network.

Implements ECDSA signing/verification over secp256k1 using only Python builtins.
Uses hashlib for SHA-256, secrets for secure random generation.
"""

import hashlib
import secrets


# --- secp256k1 curve parameters ---
# y^2 = x^3 + 7 (mod p)
_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_A = 0
_B = 7
_Gx = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
_Gy = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8
_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141


def _modinv(a: int, m: int) -> int:
    """Modular inverse using extended Euclidean algorithm."""
    if a < 0:
        a = a % m
    g, x, _ = _extended_gcd(a, m)
    if g != 1:
        raise ValueError("No modular inverse")
    return x % m


def _extended_gcd(a: int, b: int) -> tuple:
    if a == 0:
        return b, 0, 1
    g, x1, y1 = _extended_gcd(b % a, a)
    return g, y1 - (b // a) * x1, x1


# --- Elliptic curve point arithmetic ---

class Point:
    """A point on the secp256k1 curve, or the point at infinity."""
    __slots__ = ('x', 'y')

    def __init__(self, x: int | None, y: int | None):
        self.x = x
        self.y = y

    @property
    def is_infinity(self) -> bool:
        return self.x is None and self.y is None

    def __eq__(self, other):
        if not isinstance(other, Point):
            return NotImplemented
        return self.x == other.x and self.y == other.y

    def __repr__(self):
        if self.is_infinity:
            return "Point(INF)"
        return f"Point(0x{self.x:064x}, 0x{self.y:064x})"


INFINITY = Point(None, None)
G = Point(_Gx, _Gy)


def point_add(p1: Point, p2: Point) -> Point:
    """Add two points on secp256k1."""
    if p1.is_infinity:
        return p2
    if p2.is_infinity:
        return p1
    if p1.x == p2.x and p1.y != p2.y:
        return INFINITY
    if p1.x == p2.x and p1.y == p2.y:
        # Point doubling
        if p1.y == 0:
            return INFINITY
        lam = (3 * p1.x * p1.x + _A) * _modinv(2 * p1.y, _P) % _P
    else:
        lam = (p2.y - p1.y) * _modinv(p2.x - p1.x, _P) % _P
    x3 = (lam * lam - p1.x - p2.x) % _P
    y3 = (lam * (p1.x - x3) - p1.y) % _P
    return Point(x3, y3)


def point_mul(k: int, p: Point) -> Point:
    """Scalar multiplication using double-and-add."""
    result = INFINITY
    addend = p
    while k > 0:
        if k & 1:
            result = point_add(result, addend)
        addend = point_add(addend, addend)
        k >>= 1
    return result


# --- Key generation ---

def generate_keypair() -> tuple:
    """
    Generate an ECDSA keypair on secp256k1.

    Returns:
        (private_key: int, public_key: Point)
    """
    sk = secrets.randbelow(_N - 1) + 1  # 1 <= sk < N
    pk = point_mul(sk, G)
    return sk, pk


def public_key_to_bytes(pk: Point) -> bytes:
    """Serialize public key as uncompressed SEC1 format (65 bytes)."""
    return b'\x04' + pk.x.to_bytes(32, 'big') + pk.y.to_bytes(32, 'big')


def public_key_from_bytes(data: bytes) -> Point:
    """Deserialize uncompressed SEC1 public key."""
    if len(data) != 65 or data[0] != 0x04:
        raise ValueError("Invalid uncompressed public key")
    x = int.from_bytes(data[1:33], 'big')
    y = int.from_bytes(data[33:65], 'big')
    return Point(x, y)


# --- ECDSA signing ---

def _hash_message(msg: bytes) -> int:
    """SHA-256 hash of message, interpreted as integer."""
    h = hashlib.sha256(msg).digest()
    return int.from_bytes(h, 'big')


def sign(private_key: int, message: bytes) -> tuple:
    """
    Sign a message with ECDSA.

    Returns:
        (r: int, s: int) — the signature pair.
    """
    z = _hash_message(message)
    while True:
        k = secrets.randbelow(_N - 1) + 1
        p = point_mul(k, G)
        r = p.x % _N
        if r == 0:
            continue
        s = (_modinv(k, _N) * (z + r * private_key)) % _N
        if s == 0:
            continue
        # Normalize s to low-S form
        if s > _N // 2:
            s = _N - s
        return r, s


def verify(public_key: Point, message: bytes, r: int, s: int) -> bool:
    """
    Verify an ECDSA signature.

    Returns True if valid.
    """
    if not (1 <= r < _N and 1 <= s < _N):
        return False
    z = _hash_message(message)
    w = _modinv(s, _N)
    u1 = (z * w) % _N
    u2 = (r * w) % _N
    p = point_add(point_mul(u1, G), point_mul(u2, public_key))
    if p.is_infinity:
        return False
    return p.x % _N == r


def signature_to_bytes(r: int, s: int) -> bytes:
    """Serialize signature as 64 bytes (r || s), each 32 bytes big-endian."""
    return r.to_bytes(32, 'big') + s.to_bytes(32, 'big')


def signature_from_bytes(data: bytes) -> tuple:
    """Deserialize 64-byte signature."""
    if len(data) != 64:
        raise ValueError(f"Invalid signature length: {len(data)}")
    r = int.from_bytes(data[:32], 'big')
    s = int.from_bytes(data[32:64], 'big')
    return r, s
