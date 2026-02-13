# Gradatim

*Step by step* — a decentralized P2P agent network for collaborative problem-solving using shared compute.

## Overview

Gradatim is a fully custom, owned-stack mesh network where autonomous agent nodes collaborate to solve hard math problems. Each participant contributes compute — either locally or over the network — while robust verification prevents spam and bad actors.

The MVP focuses on **large integer factorization**: agents decompose the problem into subtasks (trial division ranges and Pollard's Rho attempts), distribute them across the network with redundancy, collect results, and reach consensus through majority vote with cryptographic authentication.

**Zero external dependencies.** The entire stack — elliptic curve cryptography, binary wire protocol, transport, peer discovery, reputation system, and factorization algorithms — is built from scratch using only Python standard library modules (`socket`, `threading`, `hashlib`, `struct`, `secrets`, `uuid`, `math`, `random`).

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                     Agent Node                      │
│                                                     │
│  ┌──────────┐  ┌───────────┐  ┌──────────────────┐  │
│  │ Identity │  │ Transport │  │  Task Execution  │  │
│  │ UUID +   │  │ UDP Send/ │  │  ThreadPool (4)  │  │
│  │ ECDSA    │  │ Receive   │  │  Trial Division  │  │
│  │ Keypair  │  │ :port     │  │  Pollard's Rho   │  │
│  └──────────┘  └─────┬─────┘  └────────┬─────────┘  │
│                      │                 │             │
│  ┌───────────────────┴─────────────────┴──────────┐  │
│  │              Message Dispatcher                │  │
│  │  HELLO · PEERS · ASSIGN · RESULT · VERIFY     │  │
│  └───────────────────┬────────────────────────────┘  │
│                      │                               │
│  ┌──────────┐  ┌─────┴─────┐  ┌───────────────────┐  │
│  │ Gossip   │  │ Reputation│  │ Task Aggregation  │  │
│  │ Loop     │  │ PoW+Rate  │  │ Consensus + Vote  │  │
│  │ (5s)     │  │ Limit+Rep │  │ Factor Verify     │  │
│  └──────────┘  └───────────┘  └───────────────────┘  │
└─────────────────────────────────────────────────────┘
         ▲                              ▲
         │          UDP Mesh            │
         ▼                              ▼
   ┌───────────┐                 ┌───────────┐
   │  Agent 2  │ ◄─────────────► │  Agent 3  │
   └───────────┘                 └───────────┘
```

Each agent is a standalone process with:

- **Unique identity**: UUID + ECDSA keypair on secp256k1
- **Local task queue**: receives subtask assignments, executes in a thread pool
- **Peer discovery**: bootstrap list + periodic gossip propagation
- **Result aggregation**: collects redundant results, majority-vote consensus
- **Dynamic peer management**: reputation-based; blacklists dishonest nodes

## Design Goals

1. **Own the full stack.** No LangGraph, AutoGen, or third-party frameworks. Every protocol byte, every curve multiplication, every gossip round is implemented here so the system is fully auditable and modifiable.

2. **Decentralized by default.** No central coordinator. Any agent can initiate a task, any agent can contribute compute. Peer discovery propagates organically through gossip.

3. **Trustless collaboration.** Agents don't need to trust each other. ECDSA signatures authenticate every message. Redundant task assignment (3 agents per subtask) and majority-vote consensus detect incorrect results. Reputation scoring (+10 valid, -50 invalid) ejects bad actors automatically.

4. **Extensible problem framework.** The factorization MVP demonstrates the decompose-distribute-aggregate pattern. New problem types (e.g., primality proving, discrete log, SAT solving) can be added by implementing a decomposition strategy and algorithm handler.

## Project Structure

```
gradatim/
├── __init__.py          # Package metadata, version
├── __main__.py          # Demo entry point (python -m gradatim)
├── crypto.py            # ECDSA on secp256k1 (from scratch)
├── protocol.py          # Binary wire protocol and message types
├── transport.py         # UDP network layer
├── reputation.py        # PoW, rate limiting, reputation scoring
├── factorization.py     # Trial division, Pollard's Rho, Miller-Rabin
└── agent.py             # Agent class — orchestrates everything
tests/
├── test_crypto.py       # Point arithmetic, key gen, sign/verify
├── test_protocol.py     # Serialization, payload round-trips
├── test_factorization.py# Algorithm correctness
├── test_reputation.py   # PoW, rate limiter, reputation tracker
└── test_agent.py        # Peer discovery, multi-agent factorization
```

## Modules

### `crypto.py` — Elliptic Curve Cryptography

Implements ECDSA over the **secp256k1** curve (the same curve used in Bitcoin) entirely from scratch:

- **Point arithmetic**: addition, doubling, scalar multiplication (double-and-add)
- **Key generation**: 256-bit private key via `secrets.randbelow()`, public key = `sk * G`
- **Signing**: RFC 6979-style ECDSA with low-S normalization
- **Verification**: standard ECDSA verify
- **Serialization**: uncompressed SEC1 public keys (65 bytes), 64-byte signatures (r || s)

### `protocol.py` — Binary Wire Protocol

A custom binary protocol designed for efficiency over UDP:

**Header (38 bytes):**
| Field | Size | Description |
|-------|------|-------------|
| Version | 1 byte | Protocol version (currently `1`) |
| Type | 1 byte | Message type code |
| Sender ID | 16 bytes | Agent UUID |
| Timestamp | 8 bytes | Unix timestamp (big-endian) |
| Nonce | 8 bytes | Proof-of-work nonce |
| Payload Len | 4 bytes | Payload size in bytes |

**Message types:**
| Code | Name | Purpose |
|------|------|---------|
| `0x01` | HELLO | Announce capabilities + public key |
| `0x02` | PEERS | Share known peer list |
| `0x03` | ASSIGN | Assign a factorization subtask |
| `0x04` | RESULT | Return computed factors |
| `0x05` | VERIFY | Request consensus verification |

**Payload encoding**: big-endian integers, 4-byte length-prefixed bigints and strings. Signatures (64 bytes) are appended after the payload with a 2-byte length prefix.

**Security**: every message is ECDSA-signed over the header+payload bytes. Receivers verify signatures and drop messages that are invalid, stale (>300s), or from blacklisted peers.

### `transport.py` — UDP Network Layer

Lightweight UDP transport with a background listener thread. Messages are serialized to raw bytes and sent as single datagrams (max 65,507 bytes). Malformed packets are silently dropped.

### `reputation.py` — Anti-Spam and Trust

Three-layered defense against bad actors:

| Layer | Mechanism | Parameters |
|-------|-----------|------------|
| **Proof-of-Work** | SHA-256(sender_id \|\| nonce) must have 4 leading zero bits | Computed at startup |
| **Rate Limiting** | Sliding-window per peer | 100 messages / 60 seconds |
| **Reputation** | Score tracks peer reliability | Start: 50, Valid: +10, Invalid: -50, Blacklist: <0 |

### `factorization.py` — Compute Algorithms

| Algorithm | Use Case | Details |
|-----------|----------|---------|
| **Trial Division** | Small factor search | Tests range `[start, end)` capped at `sqrt(n)+1` |
| **Pollard's Rho** | Large factor discovery | Brent cycle detection, batch GCD (128), up to 20 restarts with different `c` values |
| **Miller-Rabin** | Primality testing | 20-round probabilistic test |
| **Full Factorization** | Reference / fallback | Wheel factorization + Pollard's Rho recursion |

### `agent.py` — The Agent Class

The central orchestrator that ties everything together:

- **Lifecycle**: `start()` binds the UDP socket, computes PoW, launches gossip and task-processor threads, sends HELLO to bootstrap peers. `stop()` shuts down gracefully.
- **Peer Discovery**: HELLO exchange on first contact. Gossip loop shares peer lists every 5 seconds with a random peer.
- **Task Decomposition**: splits factorization into trial-division chunks (size = `max(1000, sqrt(n)//10)`) and 3-10 Pollard's Rho attempts with random seeds.
- **Redundant Assignment**: each subtask is sent to up to 3 agents (configurable via `REDUNDANCY_FACTOR`). The initiator also executes subtasks locally.
- **Consensus**: collects results, validates each factor (`n % f == 0`), rewards/penalizes peers, builds complete prime factorization from confirmed factors. Falls back to local computation if network results are insufficient.
- **Execution**: `ThreadPoolExecutor` with 4 workers handles subtasks in parallel.

| Constant | Value | Description |
|----------|-------|-------------|
| `REDUNDANCY_FACTOR` | 3 | Agents per subtask |
| `GOSSIP_INTERVAL` | 5s | Peer list sharing interval |
| `MAX_WORKERS` | 4 | Local thread pool size |
| `SUBTASK_TIMEOUT` | 30s | Max wait per subtask |
| `POLLARD_MAX_ITER` | 500,000 | Iterations per Rho attempt |

## Running

### Quick Demo

Run the built-in demo with 3 agents factoring several numbers collaboratively:

```bash
python -m gradatim
```

This starts three agents on `localhost` (ports 9001-9003), waits for peer discovery, then factors:

| Input | Expected Factors |
|-------|-----------------|
| 5,959 | 59 x 101 |
| 15 | 3 x 5 |
| 1,001 | 7 x 11 x 13 |
| 16,637 | 127 x 131 |
| 988,027 | 997 x 991 |

### Programmatic Usage

```python
from gradatim.agent import Agent
import time

# Start a bootstrap node
node1 = Agent(host='127.0.0.1', port=9001)
node1.start()

# Start a second node that discovers the first
node2 = Agent(host='127.0.0.1', port=9002,
              bootstrap=[('127.0.0.1', 9001)])
node2.start()

# Wait for peer discovery
time.sleep(2)

# Factor a number collaboratively
factors = node1.initiate_factorization(5959, timeout=30.0)
print(f"5959 = {' x '.join(map(str, factors))}")
# Output: 5959 = 59 x 101

# Clean up
node1.stop()
node2.stop()
```

### Running Tests

```bash
# All tests (64 total)
python -m unittest discover -s tests -v

# Individual modules
python -m unittest tests.test_crypto -v
python -m unittest tests.test_protocol -v
python -m unittest tests.test_factorization -v
python -m unittest tests.test_reputation -v
python -m unittest tests.test_agent -v
```

## How Factorization Works End-to-End

```
Agent 1 (initiator)                    Agent 2            Agent 3
    │                                     │                  │
    │  initiate_factorization(5959)       │                  │
    │                                     │                  │
    ├─ Decompose into subtasks:           │                  │
    │   [trial_div(2,78), trial_div(78,154), ..., rho(seed=X)]
    │                                     │                  │
    ├─ ASSIGN trial_div(2,78) ──────────►│                  │
    ├─ ASSIGN trial_div(2,78) ───────────────────────────►  │
    ├─ Execute trial_div(2,78) locally    │                  │
    │                                     │                  │
    ├─ ASSIGN rho(seed=42) ─────────────►│                  │
    ├─ Execute rho(seed=17) locally       │                  │
    │                                     │                  │
    │◄── RESULT [59] ────────────────────┤                  │
    │◄── RESULT [59] ───────────────────────────────────────┤
    │                                     │                  │
    ├─ Validate: 5959 % 59 == 0 ✓        │                  │
    ├─ Consensus: 3/3 agree on 59        │                  │
    ├─ Reputation: +10 to Agent 2, +10 to Agent 3           │
    │                                     │                  │
    ├─ Build complete factorization:      │                  │
    │   5959 / 59 = 101 (prime)          │                  │
    │                                     │                  │
    └─ Return [59, 101]                   │                  │
```

## Security Model

- **Authentication**: Every message is ECDSA-signed. Unsigned or incorrectly signed messages are dropped immediately.
- **Anti-replay**: Messages older than 300 seconds are rejected.
- **Sybil resistance**: Proof-of-work nonce required in every message header (4-bit difficulty).
- **DoS mitigation**: Per-peer rate limiting (100 msg/min sliding window).
- **Byzantine tolerance**: Redundant subtask assignment with majority vote. Invalid results trigger -50 reputation penalty; peers below 0 are blacklisted and all future messages are dropped.
- **Result verification**: Every claimed factor is checked (`n % factor == 0`) before acceptance.

## Requirements

- **Python 3.10+** (uses `X | Y` union type syntax)
- **No external packages** — stdlib only
- **Network**: UDP on localhost for MVP; configurable for LAN/WAN deployment

## License

MIT
