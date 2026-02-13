"""Integration tests for the Agent class."""

import logging
import time
import unittest

from gradatim.agent import Agent

logging.basicConfig(level=logging.WARNING)


class TestAgentBasic(unittest.TestCase):
    """Test basic agent lifecycle."""

    def test_start_stop(self):
        agent = Agent(host='127.0.0.1', port=0)
        agent.start()
        self.assertTrue(agent.port > 0)
        agent.stop()

    def test_unique_ids(self):
        a1 = Agent(host='127.0.0.1', port=0)
        a2 = Agent(host='127.0.0.1', port=0)
        self.assertNotEqual(a1.agent_id, a2.agent_id)


class TestPeerDiscovery(unittest.TestCase):
    """Test peer discovery via bootstrap and HELLO exchange."""

    def setUp(self):
        self.agents = []

    def tearDown(self):
        for a in self.agents:
            a.stop()

    def test_two_agents_discover_each_other(self):
        a1 = Agent(host='127.0.0.1', port=0)
        a1.start()
        self.agents.append(a1)

        a2 = Agent(host='127.0.0.1', port=0,
                    bootstrap=[('127.0.0.1', a1.port)])
        a2.start()
        self.agents.append(a2)

        # Wait for HELLO exchange
        time.sleep(2)

        self.assertGreaterEqual(a1.get_peer_count(), 1)
        self.assertGreaterEqual(a2.get_peer_count(), 1)

    def test_three_agents_mesh(self):
        a1 = Agent(host='127.0.0.1', port=0)
        a1.start()
        self.agents.append(a1)

        a2 = Agent(host='127.0.0.1', port=0,
                    bootstrap=[('127.0.0.1', a1.port)])
        a2.start()
        self.agents.append(a2)

        a3 = Agent(host='127.0.0.1', port=0,
                    bootstrap=[('127.0.0.1', a1.port)])
        a3.start()
        self.agents.append(a3)

        # Wait for gossip to propagate
        time.sleep(4)

        # All agents should know about all others
        self.assertGreaterEqual(a1.get_peer_count(), 2)
        self.assertGreaterEqual(a2.get_peer_count(), 1)
        self.assertGreaterEqual(a3.get_peer_count(), 1)


class TestFactorizationIntegration(unittest.TestCase):
    """Test collaborative factorization across agents."""

    def setUp(self):
        self.agents = []

    def tearDown(self):
        for a in self.agents:
            a.stop()

    def _setup_network(self, n_agents: int = 3) -> list:
        """Create and start n agents in a network."""
        a1 = Agent(host='127.0.0.1', port=0)
        a1.start()
        self.agents.append(a1)

        for _ in range(n_agents - 1):
            a = Agent(host='127.0.0.1', port=0,
                      bootstrap=[('127.0.0.1', a1.port)])
            a.start()
            self.agents.append(a)

        # Wait for discovery
        time.sleep(3)
        return self.agents

    def test_factor_5959(self):
        """5959 = 59 * 101"""
        agents = self._setup_network(2)
        factors = agents[0].initiate_factorization(5959, timeout=30.0)
        product = 1
        for f in factors:
            product *= f
        self.assertEqual(product, 5959)
        self.assertEqual(sorted(factors), [59, 101])

    def test_factor_15(self):
        """15 = 3 * 5"""
        agents = self._setup_network(2)
        factors = agents[0].initiate_factorization(15, timeout=15.0)
        product = 1
        for f in factors:
            product *= f
        self.assertEqual(product, 15)

    def test_factor_1001(self):
        """1001 = 7 * 11 * 13"""
        agents = self._setup_network(2)
        factors = agents[0].initiate_factorization(1001, timeout=15.0)
        product = 1
        for f in factors:
            product *= f
        self.assertEqual(product, 1001)
        self.assertEqual(sorted(factors), [7, 11, 13])

    def test_factor_semiprime(self):
        """127 * 131 = 16637"""
        agents = self._setup_network(3)
        n = 127 * 131
        factors = agents[0].initiate_factorization(n, timeout=30.0)
        product = 1
        for f in factors:
            product *= f
        self.assertEqual(product, n)

    def test_single_agent_factorization(self):
        """A single agent should still be able to factor (local execution)."""
        a = Agent(host='127.0.0.1', port=0)
        a.start()
        self.agents.append(a)
        time.sleep(1)

        factors = a.initiate_factorization(5959, timeout=15.0)
        product = 1
        for f in factors:
            product *= f
        self.assertEqual(product, 5959)


if __name__ == "__main__":
    unittest.main()
