"""
Gradatim CLI entry point.

Usage:
    python -m gradatim              Run the headless agent demo
    python -m gradatim web          Start the web UI (+ agent backend)
    python -m gradatim web --port N Specify web server port
"""

import logging
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("gradatim.main")


def run_demo():
    """Run a demo with multiple agents factorizing numbers collaboratively."""
    from .agent import Agent

    print("=" * 60)
    print("  Gradatim — Decentralized Agent Network Demo")
    print("  MVP: Collaborative Integer Factorization")
    print("=" * 60)
    print()

    # --- Start agents ---
    agent1 = Agent(host='127.0.0.1', port=9001)
    agent1.start()
    print(f"Agent 1: {agent1.agent_id} on port {agent1.port}")

    agent2 = Agent(host='127.0.0.1', port=9002,
                   bootstrap=[('127.0.0.1', 9001)])
    agent2.start()
    print(f"Agent 2: {agent2.agent_id} on port {agent2.port}")

    agent3 = Agent(host='127.0.0.1', port=9003,
                   bootstrap=[('127.0.0.1', 9001)])
    agent3.start()
    print(f"Agent 3: {agent3.agent_id} on port {agent3.port}")

    print("\nWaiting for peer discovery...")
    time.sleep(3)

    print(f"  Agent 1 peers: {agent1.get_peer_count()}")
    print(f"  Agent 2 peers: {agent2.get_peer_count()}")
    print(f"  Agent 3 peers: {agent3.get_peer_count()}")
    print()

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


def run_web(host: str = "127.0.0.1", port: int = 8080):
    """Start the web UI with a live agent backend."""
    from .agent import Agent
    from .web.server import run_server

    print("=" * 60)
    print("  Gradatim — Web Interface")
    print("=" * 60)
    print()

    # Start a local agent network (3 nodes)
    agent1 = Agent(host='127.0.0.1', port=9001)
    agent1.start()
    print(f"Agent 1 (primary): {agent1.agent_id} on port {agent1.port}")

    agent2 = Agent(host='127.0.0.1', port=9002,
                   bootstrap=[('127.0.0.1', 9001)])
    agent2.start()
    print(f"Agent 2 (worker):  {agent2.agent_id} on port {agent2.port}")

    agent3 = Agent(host='127.0.0.1', port=9003,
                   bootstrap=[('127.0.0.1', 9001)])
    agent3.start()
    print(f"Agent 3 (worker):  {agent3.agent_id} on port {agent3.port}")

    # Wait for peer discovery
    print("\nWaiting for peer discovery...")
    time.sleep(3)
    print(f"  Connected peers: {agent1.get_peer_count()}")
    print()

    try:
        # Start web server (blocks until Ctrl+C)
        run_server(host=host, port=port, agent=agent1)
    finally:
        print("\nShutting down agents...")
        agent1.stop()
        agent2.stop()
        agent3.stop()


def main():
    args = sys.argv[1:]

    if not args:
        sys.exit(run_demo())
    elif args[0] == "web":
        host = "127.0.0.1"
        port = 8080
        # Parse --port N
        if "--port" in args:
            idx = args.index("--port")
            if idx + 1 < len(args):
                port = int(args[idx + 1])
        # Parse --host H
        if "--host" in args:
            idx = args.index("--host")
            if idx + 1 < len(args):
                host = args[idx + 1]
        run_web(host=host, port=port)
    else:
        print("Usage:")
        print("  python -m gradatim          Run headless agent demo")
        print("  python -m gradatim web      Start web UI + agent backend")
        print("  python -m gradatim web --port 8080 --host 0.0.0.0")
        sys.exit(1)


if __name__ == "__main__":
    main()
