"""Tests for factorization algorithms."""

import unittest
from gradatim.factorization import (
    trial_division, pollard_rho, verify_factors, full_factorization,
    gcd, _is_probably_prime,
)


class TestGCD(unittest.TestCase):

    def test_basic(self):
        self.assertEqual(gcd(12, 8), 4)
        self.assertEqual(gcd(17, 13), 1)
        self.assertEqual(gcd(100, 75), 25)

    def test_identity(self):
        self.assertEqual(gcd(7, 0), 7)
        self.assertEqual(gcd(0, 7), 7)


class TestTrialDivision(unittest.TestCase):

    def test_small_composite(self):
        # trial_division caps at sqrt(n)+1, so for n=15 (sqrt~3.87) only 3 is found
        factors = trial_division(15, 2, 100)
        self.assertIn(3, factors)

    def test_finds_all_small_factors(self):
        # For n=100, sqrt=10, factors 2,4,5,10 are in [2, 11)
        factors = trial_division(100, 2, 100)
        self.assertIn(2, factors)
        self.assertIn(5, factors)

    def test_5959(self):
        factors = trial_division(5959, 2, 100)
        self.assertIn(59, factors)

    def test_no_factors_in_range(self):
        factors = trial_division(5959, 2, 10)
        self.assertEqual(factors, [])

    def test_prime(self):
        factors = trial_division(97, 2, 100)
        # 97 is prime, no factors in [2, 97)
        self.assertEqual(factors, [])

    def test_returns_empty_for_small_n(self):
        self.assertEqual(trial_division(0, 2, 100), [])
        self.assertEqual(trial_division(1, 2, 100), [])


class TestPollardRho(unittest.TestCase):

    def test_even_number(self):
        result = pollard_rho(100)
        self.assertIsNotNone(result)
        self.assertEqual(100 % result, 0)
        self.assertNotEqual(result, 100)

    def test_5959(self):
        result = pollard_rho(5959)
        self.assertIsNotNone(result)
        self.assertIn(result, [59, 101])

    def test_large_semiprime(self):
        n = 127 * 131  # 16637
        result = pollard_rho(n)
        self.assertIsNotNone(result)
        self.assertEqual(n % result, 0)
        self.assertIn(result, [127, 131])


class TestVerifyFactors(unittest.TestCase):

    def test_valid(self):
        self.assertTrue(verify_factors(5959, [59, 101]))
        self.assertTrue(verify_factors(15, [3, 5]))

    def test_invalid_factor(self):
        self.assertFalse(verify_factors(5959, [60]))

    def test_one_not_a_factor(self):
        self.assertFalse(verify_factors(15, [1]))


class TestFullFactorization(unittest.TestCase):

    def test_prime(self):
        self.assertEqual(full_factorization(97), [97])

    def test_5959(self):
        factors = full_factorization(5959)
        self.assertEqual(factors, [59, 101])

    def test_power_of_two(self):
        factors = full_factorization(64)
        self.assertEqual(factors, [2, 2, 2, 2, 2, 2])

    def test_1001(self):
        factors = full_factorization(1001)
        self.assertEqual(factors, [7, 11, 13])

    def test_product_equals_n(self):
        n = 997 * 991
        factors = full_factorization(n)
        product = 1
        for f in factors:
            product *= f
        self.assertEqual(product, n)

    def test_small_values(self):
        self.assertEqual(full_factorization(0), [])
        self.assertEqual(full_factorization(1), [])
        self.assertEqual(full_factorization(2), [2])
        self.assertEqual(full_factorization(3), [3])


class TestMillerRabin(unittest.TestCase):

    def test_primes(self):
        for p in [2, 3, 5, 7, 11, 13, 97, 101, 127, 131, 997, 991]:
            self.assertTrue(_is_probably_prime(p), f"{p} should be prime")

    def test_composites(self):
        for c in [4, 6, 8, 9, 15, 100, 5959, 1001]:
            self.assertFalse(_is_probably_prime(c), f"{c} should be composite")


if __name__ == "__main__":
    unittest.main()
