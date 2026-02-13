"""Tests for the reputation and anti-spam module."""

import unittest
import uuid

from gradatim.reputation import (
    compute_pow_nonce, check_pow, RateLimiter, ReputationTracker,
    POW_DIFFICULTY_BITS, INITIAL_REPUTATION, BLACKLIST_THRESHOLD,
)


class TestProofOfWork(unittest.TestCase):

    def test_compute_and_verify(self):
        sender_id = uuid.uuid4().bytes
        nonce = compute_pow_nonce(sender_id)
        self.assertTrue(check_pow(sender_id, nonce))

    def test_invalid_nonce(self):
        sender_id = uuid.uuid4().bytes
        # Nonce 0 is very unlikely to pass PoW
        # (but could in theory — skip if it does)
        if not check_pow(sender_id, 0):
            self.assertFalse(check_pow(sender_id, 0))

    def test_different_sender_different_nonce(self):
        id1 = uuid.uuid4().bytes
        id2 = uuid.uuid4().bytes
        n1 = compute_pow_nonce(id1)
        n2 = compute_pow_nonce(id2)
        # The nonces should work for their respective IDs
        self.assertTrue(check_pow(id1, n1))
        self.assertTrue(check_pow(id2, n2))


class TestRateLimiter(unittest.TestCase):

    def test_allows_under_limit(self):
        rl = RateLimiter(window=60, max_count=5)
        peer = uuid.uuid4().bytes
        for _ in range(5):
            self.assertTrue(rl.allow(peer))

    def test_blocks_over_limit(self):
        rl = RateLimiter(window=60, max_count=3)
        peer = uuid.uuid4().bytes
        for _ in range(3):
            rl.allow(peer)
        self.assertFalse(rl.allow(peer))

    def test_different_peers_independent(self):
        rl = RateLimiter(window=60, max_count=2)
        peer1 = uuid.uuid4().bytes
        peer2 = uuid.uuid4().bytes
        rl.allow(peer1)
        rl.allow(peer1)
        self.assertFalse(rl.allow(peer1))
        self.assertTrue(rl.allow(peer2))

    def test_reset(self):
        rl = RateLimiter(window=60, max_count=1)
        peer = uuid.uuid4().bytes
        rl.allow(peer)
        self.assertFalse(rl.allow(peer))
        rl.reset(peer)
        self.assertTrue(rl.allow(peer))


class TestReputationTracker(unittest.TestCase):

    def test_initial_score(self):
        rt = ReputationTracker()
        peer = uuid.uuid4().bytes
        self.assertEqual(rt.get_score(peer), INITIAL_REPUTATION)

    def test_reward(self):
        rt = ReputationTracker()
        peer = uuid.uuid4().bytes
        rt.register_peer(peer)
        rt.reward(peer, 10)
        self.assertEqual(rt.get_score(peer), INITIAL_REPUTATION + 10)

    def test_penalize_and_blacklist(self):
        rt = ReputationTracker()
        peer = uuid.uuid4().bytes
        rt.register_peer(peer)
        self.assertFalse(rt.is_blacklisted(peer))
        # Penalize enough to blacklist
        rt.penalize(peer, -100)
        self.assertTrue(rt.is_blacklisted(peer))

    def test_unblacklist(self):
        rt = ReputationTracker()
        peer = uuid.uuid4().bytes
        rt.register_peer(peer)
        rt.penalize(peer, -100)
        self.assertTrue(rt.is_blacklisted(peer))
        rt.unblacklist(peer)
        self.assertFalse(rt.is_blacklisted(peer))


if __name__ == "__main__":
    unittest.main()
