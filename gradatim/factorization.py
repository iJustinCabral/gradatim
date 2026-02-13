"""
Factorization algorithms for the MVP compute task.

Implements:
  - Trial division over a range [start, end)
  - Pollard's Rho algorithm with Brent's improvement
  - GCD utility

All implementations use Python's native arbitrary-precision integers.
"""

import math
import random


def gcd(a: int, b: int) -> int:
    """Euclidean GCD."""
    while b:
        a, b = b, a % b
    return a


def trial_division(n: int, start: int, end: int) -> list[int]:
    """
    Find factors of n by trial division in the range [start, end).

    Returns a list of factors found (may be empty).
    Each factor f satisfies: n % f == 0 and start <= f < end.
    """
    if n < 2:
        return []
    factors = []
    # Ensure start is at least 2
    start = max(start, 2)
    # Cap end at sqrt(n) + 1 for efficiency
    sqrt_n = math.isqrt(n) + 1
    end = min(end, sqrt_n + 1)

    for candidate in range(start, end):
        if n % candidate == 0:
            factors.append(candidate)
    return factors


def pollard_rho(n: int, seed: int | None = None,
                max_iterations: int = 1_000_000) -> int | None:
    """
    Pollard's Rho algorithm with Brent's cycle detection.

    Attempts to find a non-trivial factor of n. Retries with different
    parameters if the first attempt fails.

    Args:
        n: The number to factor. Must be > 1 and composite.
        seed: Starting value for the pseudorandom sequence.
        max_iterations: Maximum iterations before giving up.

    Returns:
        A non-trivial factor, or None if none found within the limit.
    """
    if n <= 1:
        return None
    if n % 2 == 0:
        return 2
    if n % 3 == 0:
        return 3

    # Try multiple c values if needed
    max_attempts = 20
    for attempt in range(max_attempts):
        if seed is not None and attempt == 0:
            x = seed % n
        else:
            x = random.randint(2, n - 1)

        c = attempt + 1  # Use deterministic c values for reproducibility
        y = x
        d = 1
        iterations = 0

        # Brent's cycle detection
        # y = "tortoise" (slow), x = "hare" (fast, moves in power-of-2 steps)
        r = 1   # current power of 2
        q = 1   # accumulated product for batch GCD

        while d == 1 and iterations < max_iterations:
            x_fixed = y  # save the tortoise position
            # Advance tortoise by r steps
            for _ in range(r):
                y = (y * y + c) % n

            # Now try to find a factor in batches
            k = 0
            while k < r and d == 1:
                ys = y  # save for backtracking
                batch = min(128, r - k)
                for _ in range(batch):
                    y = (y * y + c) % n
                    q = q * abs(x_fixed - y) % n
                    iterations += 1
                d = gcd(q, n)
                k += batch

            r *= 2

        if d == n:
            # GCD was n — backtrack step by step from ys
            d = 1
            y = ys
            while d == 1:
                y = (y * y + c) % n
                d = gcd(abs(x_fixed - y), n)

        if 1 < d < n:
            return d

    return None


def verify_factors(n: int, factors: list[int]) -> bool:
    """
    Verify that all claimed factors actually divide n.

    This is a basic check — it does not verify completeness
    (i.e., that the factors multiply to n).
    """
    for f in factors:
        if f < 2 or n % f != 0:
            return False
    return True


def full_factorization(n: int) -> list[int]:
    """
    Fully factor n into prime factors (local, single-threaded).

    Used as a reference implementation for verification.
    Returns sorted list of prime factors (with repetition).
    """
    if n < 2:
        return []
    factors = []
    # Small primes first
    for p in (2, 3, 5):
        while n % p == 0:
            factors.append(p)
            n //= p
    if n == 1:
        return factors

    # Trial division up to a reasonable limit
    candidate = 7
    increments = [4, 2, 4, 2, 4, 6, 2, 6]  # wheel for 2,3,5
    idx = 0
    while candidate * candidate <= n and candidate < 100_000:
        while n % candidate == 0:
            factors.append(candidate)
            n //= candidate
        candidate += increments[idx % len(increments)]
        idx += 1

    # Pollard's Rho for larger factors
    remaining = [n] if n > 1 else []
    while remaining:
        current = remaining.pop()
        if current == 1:
            continue
        if _is_probably_prime(current):
            factors.append(current)
            continue
        d = pollard_rho(current)
        if d is None or d == current:
            # Couldn't factor further — treat as prime
            factors.append(current)
        else:
            remaining.append(d)
            remaining.append(current // d)

    factors.sort()
    return factors


def _is_probably_prime(n: int, k: int = 20) -> bool:
    """Miller-Rabin primality test."""
    if n < 2:
        return False
    if n < 4:
        return True
    if n % 2 == 0:
        return False

    # Write n-1 as 2^r * d
    r, d = 0, n - 1
    while d % 2 == 0:
        r += 1
        d //= 2

    for _ in range(k):
        a = random.randrange(2, n - 1)
        x = pow(a, d, n)
        if x == 1 or x == n - 1:
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True
