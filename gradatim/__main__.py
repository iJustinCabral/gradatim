"""
Example usage: run a local simulation with multiple agents collaborating
to factorize integers.

Usage:
    python -m gradatim
"""

import logging
import time
import sys

from .agent import Agent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("gradatim.main")


def run_demo():
    """Run a demo with multiple agents factorizing numbers collaboratively."""
    print("=" * 60)
    print("  Gradatim — Decentralized Agent Network Demo")
    print("  MVP: Collaborative Integer Factorization")
    print("=" * 60)
    print()

    # --- Start agents ---
    # Agent 1: the initiator (bootstrap node)
    agent1 = Agent(host='127.0.0.1', port=9001)
    agent1.start()
    print(f"Agent 1: {agent1.agent_id} on port {agent1.port}")

    # Agent 2: joins via bootstrap to Agent 1
    agent2 = Agent(host='127.0.0.1', port=9002,
                   bootstrap=[('127.0.0.1', 9001)])
    agent2.start()
    print(f"Agent 2: {agent2.agent_id} on port {agent2.port}")

    # Agent 3: joins via bootstrap to Agent 1
    agent3 = Agent(host='127.0.0.1', port=9003,
                   bootstrap=[('127.0.0.1', 9001)])
    agent3.start()
    print(f"Agent 3: {agent3.agent_id} on port {agent3.port}")

    # Wait for peer discovery to propagate
    print("\nWaiting for peer discovery...")
    time.sleep(3)

    print(f"  Agent 1 peers: {agent1.get_peer_count()}")
    print(f"  Agent 2 peers: {agent2.get_peer_count()}")
    print(f"  Agent 3 peers: {agent3.get_peer_count()}")
    print()

    # --- Test cases ---
    test_cases = [
        (5959, "59 x 101"),
        (15, "3 x 5"),
        (1001, "7 x 11 x 13"),
        (127 * 131, "127 x 131 = 16637"),
        (997 * 991, "997 x 991 = 988027"),
    ]

    all_passed = True
    for n, description in test_cases:
        print(f"Factoring {n} ({description})...")
        factors = agent1.initiate_factorization(n, timeout=30.0)
        product = 1
        for f in factors:
            product *= f
        status = "PASS" if product == n else "FAIL"
        if status == "FAIL":
            all_passed = False
        print(f"  Result: {n} = {' x '.join(map(str, factors))}  [{status}]")
        print()

    # --- Cleanup ---
    print("Shutting down agents...")
    agent1.stop()
    agent2.stop()
    agent3.stop()

    print()
    if all_passed:
        print("All factorizations verified successfully!")
    else:
        print("Some factorizations failed — check logs for details.")
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(run_demo())
