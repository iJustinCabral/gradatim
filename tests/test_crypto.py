"""Tests for the crypto module."""

import unittest
from gradatim.crypto import (
    generate_keypair, sign, verify, public_key_to_bytes, public_key_from_bytes,
    signature_to_bytes, signature_from_bytes, point_mul, point_add, G, INFINITY,
    _N,
)


class TestPointArithmetic(unittest.TestCase):

    def test_infinity_identity(self):
        result = point_add(INFINITY, G)
        self.assertEqual(result, G)
        result = point_add(G, INFINITY)
        self.assertEqual(result, G)

    def test_double(self):
        p2 = point_add(G, G)
        self.assertNotEqual(p2, G)
        self.assertNotEqual(p2, INFINITY)

    def test_scalar_mul(self):
        p1 = point_mul(1, G)
        self.assertEqual(p1, G)
        p0 = point_mul(0, G)
        self.assertEqual(p0, INFINITY)

    def test_order(self):
        """n * G should be infinity (the curve order)."""
        result = point_mul(_N, G)
        self.assertTrue(result.is_infinity)


class TestKeyGen(unittest.TestCase):

    def test_generate_keypair(self):
        sk, pk = generate_keypair()
        self.assertIsInstance(sk, int)
        self.assertTrue(1 <= sk < _N)
        self.assertFalse(pk.is_infinity)

    def test_public_key_serialization(self):
        sk, pk = generate_keypair()
        data = public_key_to_bytes(pk)
        self.assertEqual(len(data), 65)
        self.assertEqual(data[0], 0x04)
        pk2 = public_key_from_bytes(data)
        self.assertEqual(pk, pk2)


class TestSignVerify(unittest.TestCase):

    def test_sign_verify_roundtrip(self):
        sk, pk = generate_keypair()
        msg = b"hello world"
        r, s = sign(sk, msg)
        self.assertTrue(verify(pk, msg, r, s))

    def test_verify_wrong_message(self):
        sk, pk = generate_keypair()
        r, s = sign(sk, b"message A")
        self.assertFalse(verify(pk, b"message B", r, s))

    def test_verify_wrong_key(self):
        sk1, pk1 = generate_keypair()
        _, pk2 = generate_keypair()
        r, s = sign(sk1, b"test")
        self.assertFalse(verify(pk2, b"test", r, s))

    def test_signature_serialization(self):
        sk, pk = generate_keypair()
        r, s = sign(sk, b"data")
        data = signature_to_bytes(r, s)
        self.assertEqual(len(data), 64)
        r2, s2 = signature_from_bytes(data)
        self.assertEqual(r, r2)
        self.assertEqual(s, s2)


if __name__ == "__main__":
    unittest.main()
