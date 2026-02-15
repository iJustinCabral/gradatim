"""
Solvers for additional math problem types beyond factorization.

Implements:
  - Goldbach conjecture verification (express even n as sum of two primes)
  - Collatz sequence computation (3n+1 problem)
  - Perfect number search in a range
  - Distributed primality testing (Miller-Rabin with many witnesses)

These connect open/unsolved problems in mathematics to the compute network.
"""

import random

from .factorization import _is_probably_prime


def goldbach_decomposition(n: int) -> tuple[int, int]:
    """
    Find two primes p, q such that p + q = n.

    The Goldbach conjecture (1742) states every even integer > 2 is the sum
    of two primes. Verified computationally up to 4 x 10^18 but unproven.

    Raises ValueError if n is odd, < 4, or if no decomposition is found
    (which would disprove the conjecture for that n).
    """
    if n < 4 or n % 2 != 0:
        raise ValueError(f"Goldbach requires even n >= 4, got {n}")

    # Special case
    if n == 4:
        return (2, 2)

    # Try p = 3, 5, 7, ... (odd primes) and check if n - p is also prime
    # Start with 3 since one of the two primes must be odd for n > 4
    for p in range(3, n // 2 + 1, 2):
        if _is_probably_prime(p) and _is_probably_prime(n - p):
            return (p, n - p)

    raise ValueError(f"No Goldbach decomposition found for {n} — "
                     f"this would be a counterexample to the conjecture!")


def collatz_sequence(start: int, max_steps: int = 10_000_000) -> tuple[int, int, bool]:
    """
    Compute the Collatz sequence from a starting value.

    The Collatz conjecture (1937) states that for any positive integer:
      - If even, divide by 2
      - If odd, multiply by 3 and add 1
    The sequence always reaches 1. Verified up to ~10^20 but unproven.

    Returns (sequence_length, max_value_reached, reached_one).
    """
    if start < 1:
        raise ValueError(f"Start must be >= 1, got {start}")

    n = start
    length = 0
    max_val = start

    while n != 1 and length < max_steps:
        if n % 2 == 0:
            n = n // 2
        else:
            n = 3 * n + 1
        length += 1
        if n > max_val:
            max_val = n

    return (length, max_val, n == 1)


def find_perfect_numbers(lo: int, hi: int) -> list[int]:
    """
    Find all perfect numbers in [lo, hi].

    A perfect number equals the sum of its proper divisors (e.g. 6 = 1+2+3).
    Only 51 are known as of 2024, all even. Whether odd perfect numbers exist
    is an open problem dating back over 2000 years.

    For efficiency, checks known Mersenne-prime-based perfect numbers first,
    then brute-forces the remainder for small ranges.
    """
    # All known even perfect numbers are of the form 2^(p-1) * (2^p - 1)
    # where 2^p - 1 is a Mersenne prime. Check the small Mersenne exponents.
    mersenne_exponents = [2, 3, 5, 7, 13, 17, 19, 31]
    known = []
    for p in mersenne_exponents:
        mp = (1 << p) - 1  # 2^p - 1
        if _is_probably_prime(mp):
            perfect = (1 << (p - 1)) * mp
            if lo <= perfect <= hi:
                known.append(perfect)

    # For small ranges, also brute-force (catches any odd perfect if it exists)
    if hi - lo < 100_000 and hi <= 10_000_000:
        for n in range(max(lo, 2), hi + 1):
            if n in known:
                continue
            if _sum_proper_divisors(n) == n:
                known.append(n)

    known.sort()
    return known


def _sum_proper_divisors(n: int) -> int:
    """Sum of proper divisors of n (excluding n itself)."""
    if n <= 1:
        return 0
    total = 1  # 1 is always a divisor
    i = 2
    while i * i <= n:
        if n % i == 0:
            total += i
            other = n // i
            if other != i:
                total += other
        i += 1
    return total


def primality_test(n: int, witnesses: int = 64) -> tuple[bool, int]:
    """
    Distributed-style primality test using Miller-Rabin with many witnesses.

    For numbers < 3.3 x 10^24, deterministic witnesses exist. For larger
    numbers, 64 random witnesses gives a false positive probability of < 2^-128.

    Returns (is_probably_prime, number_of_witnesses_used).
    """
    if n < 2:
        return False, 0
    if n < 4:
        return True, 1
    if n % 2 == 0:
        return False, 1

    # For small n, use deterministic witnesses
    if n < 3_317_044_064_679_887_385_961_981:
        deterministic = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37]
        for a in deterministic:
            if a >= n:
                continue
            if not _miller_rabin_witness(n, a):
                return False, deterministic.index(a) + 1
        return True, len([a for a in deterministic if a < n])

    # For large n, use random witnesses
    r, d = 0, n - 1
    while d % 2 == 0:
        r += 1
        d //= 2

    tested = set()
    for _ in range(witnesses):
        a = random.randrange(2, n - 1)
        while a in tested:
            a = random.randrange(2, n - 1)
        tested.add(a)
        if not _miller_rabin_witness(n, a):
            return False, len(tested)

    return True, witnesses


def _miller_rabin_witness(n: int, a: int) -> bool:
    """
    Test if n passes the Miller-Rabin test for witness a.

    Returns True if n is *probably* prime for this witness,
    False if n is *definitely* composite.
    """
    r, d = 0, n - 1
    while d % 2 == 0:
        r += 1
        d //= 2

    x = pow(a, d, n)
    if x == 1 or x == n - 1:
        return True
    for _ in range(r - 1):
        x = pow(x, 2, n)
        if x == n - 1:
            return True
    return False
