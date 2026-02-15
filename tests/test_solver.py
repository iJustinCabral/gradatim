"""Tests for the additional math problem solvers."""

import unittest
from gradatim._solver import (
    goldbach_decomposition,
    collatz_sequence,
    find_perfect_numbers,
    primality_test,
    _sum_proper_divisors,
)


class TestGoldbach(unittest.TestCase):

    def test_small_even(self):
        p, q = goldbach_decomposition(4)
        self.assertEqual(p + q, 4)

    def test_10(self):
        p, q = goldbach_decomposition(10)
        self.assertEqual(p + q, 10)

    def test_100(self):
        p, q = goldbach_decomposition(100)
        self.assertEqual(p + q, 100)

    def test_large(self):
        p, q = goldbach_decomposition(1000000)
        self.assertEqual(p + q, 1000000)

    def test_primes_are_prime(self):
        from gradatim.factorization import _is_probably_prime
        for n in [10, 20, 50, 100, 1000, 10000]:
            p, q = goldbach_decomposition(n)
            self.assertTrue(_is_probably_prime(p), f"{p} not prime for n={n}")
            self.assertTrue(_is_probably_prime(q), f"{q} not prime for n={n}")

    def test_odd_raises(self):
        with self.assertRaises(ValueError):
            goldbach_decomposition(7)

    def test_too_small_raises(self):
        with self.assertRaises(ValueError):
            goldbach_decomposition(2)


class TestCollatz(unittest.TestCase):

    def test_one(self):
        length, max_val, reached = collatz_sequence(1)
        self.assertEqual(length, 0)
        self.assertTrue(reached)

    def test_two(self):
        length, max_val, reached = collatz_sequence(2)
        self.assertEqual(length, 1)
        self.assertTrue(reached)

    def test_27(self):
        """27 is famous for its long sequence (111 steps, max 9232)."""
        length, max_val, reached = collatz_sequence(27)
        self.assertEqual(length, 111)
        self.assertEqual(max_val, 9232)
        self.assertTrue(reached)

    def test_large(self):
        length, max_val, reached = collatz_sequence(1000000)
        self.assertTrue(reached)
        self.assertGreater(length, 0)


class TestPerfectNumbers(unittest.TestCase):

    def test_sum_divisors(self):
        self.assertEqual(_sum_proper_divisors(6), 6)      # 1+2+3
        self.assertEqual(_sum_proper_divisors(28), 28)     # 1+2+4+7+14
        self.assertEqual(_sum_proper_divisors(12), 16)     # 1+2+3+4+6

    def test_known_small(self):
        found = find_perfect_numbers(1, 10000)
        self.assertIn(6, found)
        self.assertIn(28, found)
        self.assertIn(496, found)
        self.assertIn(8128, found)
        self.assertEqual(len(found), 4)

    def test_range_miss(self):
        found = find_perfect_numbers(7, 27)
        self.assertEqual(found, [])

    def test_large_range(self):
        """33550336 is the 5th perfect number."""
        found = find_perfect_numbers(1, 100000000)
        self.assertIn(6, found)
        self.assertIn(28, found)
        self.assertIn(496, found)
        self.assertIn(8128, found)
        self.assertIn(33550336, found)


class TestPrimality(unittest.TestCase):

    def test_small_primes(self):
        for p in [2, 3, 5, 7, 11, 97, 101]:
            is_p, _ = primality_test(p)
            self.assertTrue(is_p, f"{p} should be prime")

    def test_small_composites(self):
        for c in [4, 6, 9, 15, 100]:
            is_p, _ = primality_test(c)
            self.assertFalse(is_p, f"{c} should be composite")

    def test_mersenne_127(self):
        """2^127 - 1 is a Mersenne prime."""
        n = (2**127) - 1
        is_p, witnesses = primality_test(n)
        self.assertTrue(is_p)
        self.assertGreater(witnesses, 0)

    def test_mersenne_composite(self):
        """2^11 - 1 = 2047 = 23 * 89 is NOT prime."""
        is_p, _ = primality_test(2047)
        self.assertFalse(is_p)


if __name__ == "__main__":
    unittest.main()
