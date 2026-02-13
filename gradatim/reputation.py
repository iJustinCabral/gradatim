"""
Reputation system and anti-spam measures.

- Proof-of-Work (PoW) nonce requirement on messages.
- Per-peer rate limiting.
- Reputation scoring: +10 for valid results, -50 for invalid; blacklist if < 0.
"""

import hashlib
import time
import threading


# PoW difficulty: the SHA-256 of (sender_id || nonce) must have this many
# leading zero bits. Low for MVP (4 bits = first hex nibble is 0).
POW_DIFFICULTY_BITS = 4

# Rate limiting: max messages per window from a single peer
RATE_LIMIT_WINDOW = 60   # seconds
RATE_LIMIT_MAX = 100      # messages per window

# Reputation scores
REWARD_VALID_RESULT = 10
PENALTY_INVALID_RESULT = -50
INITIAL_REPUTATION = 50
BLACKLIST_THRESHOLD = 0


def compute_pow_nonce(sender_id: bytes, difficulty_bits: int = POW_DIFFICULTY_BITS) -> int:
    """
    Find a nonce such that SHA-256(sender_id || nonce_bytes) has at least
    `difficulty_bits` leading zero bits.
    """
    nonce = 0
    while True:
        if check_pow(sender_id, nonce, difficulty_bits):
            return nonce
        nonce += 1


def check_pow(sender_id: bytes, nonce: int, difficulty_bits: int = POW_DIFFICULTY_BITS) -> bool:
    """Verify a proof-of-work nonce."""
    data = sender_id + nonce.to_bytes(8, 'big')
    h = hashlib.sha256(data).digest()
    # Check leading zero bits
    bits_to_check = difficulty_bits
    for byte in h:
        if bits_to_check <= 0:
            break
        if bits_to_check >= 8:
            if byte != 0:
                return False
            bits_to_check -= 8
        else:
            mask = (0xFF << (8 - bits_to_check)) & 0xFF
            if byte & mask != 0:
                return False
            bits_to_check = 0
    return True


class RateLimiter:
    """Per-peer sliding-window rate limiter."""

    def __init__(self, window: float = RATE_LIMIT_WINDOW,
                 max_count: int = RATE_LIMIT_MAX):
        self._window = window
        self._max_count = max_count
        self._lock = threading.Lock()
        # peer_id -> list of timestamps
        self._records: dict[bytes, list[float]] = {}

    def allow(self, peer_id: bytes) -> bool:
        """Check if a message from peer_id is allowed. Records it if so."""
        now = time.time()
        cutoff = now - self._window
        with self._lock:
            timestamps = self._records.get(peer_id, [])
            # Prune old entries
            timestamps = [t for t in timestamps if t > cutoff]
            if len(timestamps) >= self._max_count:
                self._records[peer_id] = timestamps
                return False
            timestamps.append(now)
            self._records[peer_id] = timestamps
            return True

    def reset(self, peer_id: bytes):
        """Clear records for a peer."""
        with self._lock:
            self._records.pop(peer_id, None)


class ReputationTracker:
    """
    Track reputation scores for peers.

    Peers start at INITIAL_REPUTATION. Scores change based on behavior.
    Peers with score < BLACKLIST_THRESHOLD are blacklisted.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._scores: dict[bytes, int] = {}
        self._blacklist: set[bytes] = set()

    def get_score(self, peer_id: bytes) -> int:
        with self._lock:
            return self._scores.get(peer_id, INITIAL_REPUTATION)

    def is_blacklisted(self, peer_id: bytes) -> bool:
        with self._lock:
            return peer_id in self._blacklist

    def register_peer(self, peer_id: bytes):
        """Register a new peer with initial reputation."""
        with self._lock:
            if peer_id not in self._scores:
                self._scores[peer_id] = INITIAL_REPUTATION

    def reward(self, peer_id: bytes, amount: int = REWARD_VALID_RESULT):
        """Increase peer's reputation for good behavior."""
        with self._lock:
            self._scores[peer_id] = self._scores.get(peer_id, INITIAL_REPUTATION) + amount

    def penalize(self, peer_id: bytes, amount: int = PENALTY_INVALID_RESULT):
        """
        Decrease peer's reputation for bad behavior.
        Blacklists if score drops below threshold.
        """
        with self._lock:
            current = self._scores.get(peer_id, INITIAL_REPUTATION)
            new_score = current + amount  # amount is negative
            self._scores[peer_id] = new_score
            if new_score < BLACKLIST_THRESHOLD:
                self._blacklist.add(peer_id)

    def unblacklist(self, peer_id: bytes):
        """Remove a peer from the blacklist (manual override)."""
        with self._lock:
            self._blacklist.discard(peer_id)

    def get_all_scores(self) -> dict[bytes, int]:
        with self._lock:
            return dict(self._scores)
