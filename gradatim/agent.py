"""
The Agent class — a standalone node in the decentralized P2P mesh network.

Each agent:
  - Has a unique UUID and ECDSA keypair.
  - Maintains a local task queue.
  - Discovers peers via bootstrap list and gossip.
  - Executes subtasks (factorization) in worker threads.
  - Aggregates and verifies results with redundant consensus.
"""

import logging
import math
import queue
import random
import threading
import time
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from . import crypto
from . import protocol
from . import factorization
from .transport import UDPTransport
from .reputation import (
    ReputationTracker, RateLimiter, compute_pow_nonce, check_pow,
    REWARD_VALID_RESULT, PENALTY_INVALID_RESULT,
)

logger = logging.getLogger(__name__)

# How many agents should redundantly compute each subtask for consensus
REDUNDANCY_FACTOR = 3

# Timeout waiting for subtask results (seconds)
SUBTASK_TIMEOUT = 30

# Gossip interval (seconds)
GOSSIP_INTERVAL = 5

# Worker pool size for executing subtasks
MAX_WORKERS = 4

# Max Pollard's Rho iterations per subtask
POLLARD_MAX_ITER = 500_000


class PeerInfo:
    """Information about a known peer."""
    __slots__ = ('peer_id', 'host', 'port', 'public_key', 'capabilities', 'last_seen')

    def __init__(self, peer_id: bytes, host: str, port: int,
                 public_key: crypto.Point | None = None,
                 capabilities: list[str] | None = None):
        self.peer_id = peer_id
        self.host = host
        self.port = port
        self.public_key = public_key
        self.capabilities = capabilities or []
        self.last_seen = time.time()


class TaskState:
    """Tracks the state of a factorization task initiated by this agent."""

    def __init__(self, task_id: uuid.UUID, n: int, num_subtasks: int):
        self.task_id = task_id
        self.n = n
        self.num_subtasks = num_subtasks
        self.lock = threading.Lock()
        # subtask_index -> {sender_id: [factors]}
        self.results: dict[int, dict[bytes, list[int]]] = defaultdict(dict)
        self.completed = threading.Event()
        self.final_factors: list[int] = []
        self.created_at = time.time()

    def add_result(self, subtask_index: int, sender_id: bytes,
                   factors: list[int]):
        with self.lock:
            self.results[subtask_index][sender_id] = factors

    def is_complete(self) -> bool:
        """Check if we have enough results to reach consensus on all subtasks."""
        with self.lock:
            for i in range(self.num_subtasks):
                if len(self.results.get(i, {})) < 1:
                    return False
        return True


class Agent:
    """
    A standalone agent node in the decentralized P2P mesh.

    Usage:
        agent = Agent(host='127.0.0.1', port=9001, bootstrap=[('127.0.0.1', 9000)])
        agent.start()
        result = agent.initiate_factorization(5959)
        agent.stop()
    """

    def __init__(self, host: str = '127.0.0.1', port: int = 0,
                 bootstrap: list[tuple] | None = None,
                 capabilities: list[str] | None = None):
        # Identity
        self.agent_id = uuid.uuid4()
        self.agent_id_bytes = self.agent_id.bytes
        self._private_key, self.public_key = crypto.generate_keypair()

        # Network
        self.host = host
        self.port = port
        self._bootstrap = bootstrap or []
        self.capabilities = capabilities or ['trial_division', 'pollard_rho']

        # Peer management
        self._peers_lock = threading.Lock()
        self._peers: dict[bytes, PeerInfo] = {}  # peer_id_bytes -> PeerInfo

        # Transport
        self._transport = UDPTransport(host, port, self._on_message_received)

        # Task management
        self._task_queue: queue.Queue = queue.Queue()
        self._active_tasks: dict[uuid.UUID, TaskState] = {}
        self._tasks_lock = threading.Lock()

        # Subtask tracking: task_id -> {subtask_index: [(peer_id, factors)]}
        self._subtask_assignments: dict[uuid.UUID, dict] = {}
        self._assignments_lock = threading.Lock()

        # Anti-spam / reputation
        self._reputation = ReputationTracker()
        self._rate_limiter = RateLimiter()

        # PoW nonce for our messages
        self._pow_nonce = 0

        # Worker pool for subtask execution
        self._executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

        # Control
        self._running = False
        self._gossip_thread = None
        self._task_processor_thread = None

        # Result callbacks for initiated tasks
        self._result_events: dict[uuid.UUID, threading.Event] = {}
        self._result_values: dict[uuid.UUID, list[int]] = {}

    @property
    def address(self) -> tuple:
        return (self.host, self.port)

    def start(self):
        """Start the agent: bind transport, compute PoW, begin gossip."""
        logger.info("Agent %s starting on %s:%d", self.agent_id, self.host, self.port)

        # Compute our PoW nonce
        self._pow_nonce = compute_pow_nonce(self.agent_id_bytes)

        # Start transport
        self._transport.start()
        # Get the actual bound port (useful if port=0)
        self.port = self._transport._sock.getsockname()[1]
        self._transport.port = self.port

        self._running = True

        # Start gossip thread
        self._gossip_thread = threading.Thread(
            target=self._gossip_loop, daemon=True, name=f"gossip-{self.port}"
        )
        self._gossip_thread.start()

        # Start task processor thread
        self._task_processor_thread = threading.Thread(
            target=self._task_processor_loop, daemon=True,
            name=f"tasks-{self.port}"
        )
        self._task_processor_thread.start()

        # Send HELLO to bootstrap peers
        for addr in self._bootstrap:
            self._send_hello(addr)

        logger.info("Agent %s started on port %d", self.agent_id, self.port)

    def stop(self):
        """Shut down the agent gracefully."""
        self._running = False
        self._executor.shutdown(wait=False)
        self._transport.stop()
        if self._gossip_thread:
            self._gossip_thread.join(timeout=3.0)
        if self._task_processor_thread:
            self._task_processor_thread.join(timeout=3.0)
        logger.info("Agent %s stopped", self.agent_id)

    # --- Public API ---

    def initiate_factorization(self, n: int, timeout: float = 60.0) -> list[int]:
        """
        Initiate a collaborative factorization of n across the network.

        Decomposes the problem into subtasks, assigns them to peers
        (with redundancy), collects results, and reaches consensus.

        Returns sorted list of prime factors of n, or partial factors
        if timeout is reached.
        """
        logger.info("Agent %s initiating factorization of %d", self.agent_id, n)

        if n < 2:
            return []

        task_id = uuid.uuid4()
        subtasks = self._decompose_factorization(n)

        # Create task state
        task_state = TaskState(task_id, n, len(subtasks))
        with self._tasks_lock:
            self._active_tasks[task_id] = task_state

        # Set up result event
        result_event = threading.Event()
        self._result_events[task_id] = result_event
        self._result_values[task_id] = []

        # Get available peers
        peers = self._get_active_peers()
        all_workers = peers + [None]  # None = self

        # Track assignments for consensus
        with self._assignments_lock:
            self._subtask_assignments[task_id] = {}

        # Assign subtasks
        for i, subtask in enumerate(subtasks):
            # Select workers with redundancy
            num_workers = min(REDUNDANCY_FACTOR, len(all_workers))
            selected = random.sample(all_workers, num_workers)

            with self._assignments_lock:
                self._subtask_assignments[task_id][i] = {
                    'subtask': subtask,
                    'assigned_to': [],
                    'results': {},
                }

            for worker in selected:
                if worker is None:
                    # Execute locally
                    self._execute_subtask_local(task_id, i, subtask)
                    with self._assignments_lock:
                        self._subtask_assignments[task_id][i]['assigned_to'].append(
                            self.agent_id_bytes
                        )
                else:
                    # Send to peer
                    self._assign_to_peer(task_id, i, subtask, worker)
                    with self._assignments_lock:
                        self._subtask_assignments[task_id][i]['assigned_to'].append(
                            worker.peer_id
                        )

        # Wait for results
        deadline = time.time() + timeout
        while time.time() < deadline:
            if result_event.wait(timeout=1.0):
                break
            # Check if we have enough results
            self._try_aggregate(task_id)

        # Final aggregation
        factors = self._aggregate_results(task_id, n)

        # Cleanup
        self._result_events.pop(task_id, None)
        self._result_values.pop(task_id, None)
        with self._tasks_lock:
            self._active_tasks.pop(task_id, None)

        return factors

    def get_peer_count(self) -> int:
        """Return number of known peers."""
        with self._peers_lock:
            return len(self._peers)

    def get_peers(self) -> list[PeerInfo]:
        """Return list of known peers."""
        with self._peers_lock:
            return list(self._peers.values())

    # --- Message sending ---

    def _send_message(self, msg_type: int, payload: bytes, addr: tuple):
        """Build, sign, and send a protocol message."""
        msg = protocol.Message(
            msg_type=msg_type,
            sender_id=self.agent_id_bytes,
            payload=payload,
            nonce=self._pow_nonce,
        )
        msg.sign(self._private_key)
        try:
            self._transport.send(msg, addr)
        except (OSError, ValueError) as e:
            logger.warning("Failed to send message to %s: %s", addr, e)

    def _send_hello(self, addr: tuple):
        """Send a HELLO message to a peer."""
        payload = protocol.build_hello_payload(
            self.capabilities, self.public_key, self.port
        )
        self._send_message(protocol.MSG_HELLO, payload, addr)

    def _send_peers(self, addr: tuple):
        """Send our peer list to a peer."""
        with self._peers_lock:
            peer_list = [
                (p.peer_id, p.host, p.port) for p in self._peers.values()
            ]
        if not peer_list:
            return
        # Send at most 20 peers
        peer_list = peer_list[:20]
        payload = protocol.build_peers_payload(peer_list)
        self._send_message(protocol.MSG_PEERS, payload, addr)

    def _assign_to_peer(self, task_id: uuid.UUID, subtask_index: int,
                        subtask: dict, peer: PeerInfo):
        """Send an ASSIGN message to a peer for a subtask."""
        # Encode subtask_index into the task_id namespace
        # by creating a sub-UUID that encodes the index
        sub_task_id = uuid.UUID(
            int=(task_id.int & 0xFFFFFFFFFFFFFFFFFFFFFFFF00000000) | subtask_index
        )
        payload = protocol.build_assign_payload(
            sub_task_id, subtask['algorithm'], subtask['params']
        )
        self._send_message(protocol.MSG_ASSIGN, payload, (peer.host, peer.port))

    # --- Message handling ---

    def _on_message_received(self, msg: protocol.Message, addr: tuple):
        """
        Top-level message handler called by the transport layer.

        Validates PoW, rate limiting, staleness, signature, then dispatches.
        """
        sender_id = msg.sender_id

        # Don't process our own messages
        if sender_id == self.agent_id_bytes:
            return

        # Check blacklist
        if self._reputation.is_blacklisted(sender_id):
            logger.debug("Dropping message from blacklisted peer %s", sender_id.hex()[:8])
            return

        # Check staleness
        if msg.is_stale():
            logger.debug("Dropping stale message from %s", sender_id.hex()[:8])
            return

        # Check PoW
        if not check_pow(sender_id, msg.nonce):
            logger.debug("Dropping message with invalid PoW from %s", sender_id.hex()[:8])
            return

        # Rate limiting
        if not self._rate_limiter.allow(sender_id):
            logger.debug("Rate limiting peer %s", sender_id.hex()[:8])
            return

        # Verify signature (need peer's public key)
        peer = self._get_peer(sender_id)
        if peer and peer.public_key:
            if not msg.verify_signature(peer.public_key):
                logger.warning("Invalid signature from %s", sender_id.hex()[:8])
                self._reputation.penalize(sender_id)
                return
        elif msg.msg_type != protocol.MSG_HELLO:
            # For non-HELLO messages from unknown peers, we can't verify sig
            # Accept but mark as unverified
            logger.debug("Accepting unverified message from unknown peer %s",
                         sender_id.hex()[:8])

        # Dispatch by type
        handlers = {
            protocol.MSG_HELLO: self._handle_hello,
            protocol.MSG_PEERS: self._handle_peers,
            protocol.MSG_ASSIGN: self._handle_assign,
            protocol.MSG_RESULT: self._handle_result,
            protocol.MSG_VERIFY: self._handle_verify,
        }
        handler = handlers.get(msg.msg_type)
        if handler:
            try:
                handler(msg, addr)
            except Exception:
                logger.exception("Error handling message type %d from %s",
                                 msg.msg_type, sender_id.hex()[:8])
        else:
            logger.debug("Unknown message type %d from %s",
                         msg.msg_type, sender_id.hex()[:8])

    def _handle_hello(self, msg: protocol.Message, addr: tuple):
        """Handle a HELLO message: register peer, verify sig, reply."""
        parsed = protocol.parse_hello_payload(msg.payload)
        public_key = parsed['public_key']
        capabilities = parsed['capabilities']
        listen_port = parsed['listen_port']

        # Now that we have the public key, verify the signature
        if not msg.verify_signature(public_key):
            logger.warning("HELLO with invalid signature from %s", addr)
            return

        # Register peer
        peer_host = addr[0]
        peer_port = listen_port
        peer_info = PeerInfo(
            peer_id=msg.sender_id,
            host=peer_host,
            port=peer_port,
            public_key=public_key,
            capabilities=capabilities,
        )

        with self._peers_lock:
            is_new = msg.sender_id not in self._peers
            self._peers[msg.sender_id] = peer_info

        self._reputation.register_peer(msg.sender_id)

        logger.info("Registered peer %s at %s:%d (caps: %s)",
                     msg.sender_id.hex()[:8], peer_host, peer_port, capabilities)

        # Send HELLO back if this is a new peer
        if is_new:
            self._send_hello((peer_host, peer_port))
            # Also share our peer list
            self._send_peers((peer_host, peer_port))

    def _handle_peers(self, msg: protocol.Message, addr: tuple):
        """Handle a PEERS message: discover new peers."""
        peers = protocol.parse_peers_payload(msg.payload)
        for peer_id_bytes, host, port in peers:
            if peer_id_bytes == self.agent_id_bytes:
                continue
            with self._peers_lock:
                if peer_id_bytes not in self._peers:
                    # New peer — send HELLO to discover
                    peer_info = PeerInfo(peer_id=peer_id_bytes, host=host, port=port)
                    self._peers[peer_id_bytes] = peer_info
                    self._send_hello((host, port))

    def _handle_assign(self, msg: protocol.Message, addr: tuple):
        """Handle an ASSIGN message: execute the subtask."""
        parsed = protocol.parse_assign_payload(msg.payload)
        task_id = parsed['task_id']
        algorithm = parsed['algorithm']
        params = parsed['params']

        logger.info("Received ASSIGN task=%s algo=%s from %s",
                     task_id, algorithm, msg.sender_id.hex()[:8])

        # Queue execution
        self._task_queue.put({
            'task_id': task_id,
            'algorithm': algorithm,
            'params': params,
            'requester_id': msg.sender_id,
            'requester_addr': addr,
        })

    def _handle_result(self, msg: protocol.Message, addr: tuple):
        """Handle a RESULT message: collect for aggregation."""
        parsed = protocol.parse_result_payload(msg.payload)
        task_id = parsed['task_id']
        factors = parsed['factors']
        status = parsed['status']

        logger.info("Received RESULT task=%s factors=%s status=%s from %s",
                     task_id, factors, status, msg.sender_id.hex()[:8])

        # Extract subtask index from task_id
        subtask_index = task_id.int & 0xFFFFFFFF
        # Reconstruct the parent task_id
        parent_task_int = task_id.int & 0xFFFFFFFFFFFFFFFFFFFFFFFF00000000

        # Find matching active task
        with self._tasks_lock:
            matching_task = None
            for tid, state in self._active_tasks.items():
                if (tid.int & 0xFFFFFFFFFFFFFFFFFFFFFFFF00000000) == parent_task_int:
                    matching_task = state
                    break

        if matching_task is None:
            logger.debug("Result for unknown task %s", task_id)
            return

        # Validate factors
        n = matching_task.n
        valid = all(f > 1 and n % f == 0 for f in factors)

        if valid:
            self._reputation.reward(msg.sender_id)
        else:
            self._reputation.penalize(msg.sender_id)
            logger.warning("Invalid factors from %s for task %s",
                           msg.sender_id.hex()[:8], task_id)
            return

        # Store result
        matching_task.add_result(subtask_index, msg.sender_id, factors)

        # Check if task is complete
        self._try_aggregate(matching_task.task_id)

    def _handle_verify(self, msg: protocol.Message, addr: tuple):
        """Handle a VERIFY request: check claimed factors and respond."""
        parsed = protocol.parse_verify_payload(msg.payload)
        n = parsed['n']
        claimed_factors = parsed['claimed_factors']

        valid = factorization.verify_factors(n, claimed_factors)
        # Respond with a RESULT indicating verification status
        status = 'verified' if valid else 'rejected'
        payload = protocol.build_result_payload(
            parsed['task_id'], claimed_factors, status
        )
        self._send_message(protocol.MSG_RESULT, payload, addr)

    # --- Task execution ---

    def _task_processor_loop(self):
        """Process subtasks from the local queue."""
        while self._running:
            try:
                task = self._task_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            # Submit to thread pool
            self._executor.submit(self._execute_remote_subtask, task)

    def _execute_remote_subtask(self, task: dict):
        """Execute a subtask assigned by a remote peer and send back results."""
        task_id = task['task_id']
        algorithm = task['algorithm']
        params = task['params']
        requester_addr = task['requester_addr']

        try:
            factors = self._run_algorithm(algorithm, params)
        except Exception:
            logger.exception("Error executing subtask %s", task_id)
            factors = []

        # Send result back
        payload = protocol.build_result_payload(task_id, factors)
        self._send_message(protocol.MSG_RESULT, payload, requester_addr)

    def _execute_subtask_local(self, task_id: uuid.UUID, subtask_index: int,
                               subtask: dict):
        """Execute a subtask locally (for self-assigned work)."""
        def _run():
            try:
                factors = self._run_algorithm(
                    subtask['algorithm'], subtask['params']
                )
            except Exception:
                logger.exception("Error in local subtask %d of %s",
                                 subtask_index, task_id)
                factors = []

            # Store result directly
            with self._tasks_lock:
                state = self._active_tasks.get(task_id)
            if state:
                state.add_result(subtask_index, self.agent_id_bytes, factors)
                self._try_aggregate(task_id)

        self._executor.submit(_run)

    def _run_algorithm(self, algorithm: str, params: dict) -> list[int]:
        """Execute a factorization algorithm with the given params."""
        n = params.get('n', 0)
        if algorithm == 'trial_division':
            start = params.get('start', 2)
            end = params.get('end', 0)
            return factorization.trial_division(n, start, end)
        elif algorithm == 'pollard_rho':
            seed = params.get('seed', None)
            max_iter = params.get('max_iterations', POLLARD_MAX_ITER)
            result = factorization.pollard_rho(n, seed=seed, max_iterations=max_iter)
            return [result] if result else []
        else:
            logger.warning("Unknown algorithm: %s", algorithm)
            return []

    # --- Task decomposition ---

    def _decompose_factorization(self, n: int) -> list[dict]:
        """
        Decompose a factorization problem into subtasks.

        Strategy:
          1. Trial division chunks over [2, sqrt(n)] split into ranges.
          2. Multiple Pollard's Rho attempts with different seeds.
        """
        subtasks = []
        sqrt_n = math.isqrt(n)

        # Trial division: split into chunks
        chunk_size = max(1000, sqrt_n // 10)
        start = 2
        while start <= sqrt_n:
            end = min(start + chunk_size, sqrt_n + 1)
            subtasks.append({
                'algorithm': 'trial_division',
                'params': {'n': n, 'start': start, 'end': end},
            })
            start = end

        # Pollard's Rho: multiple attempts with random seeds
        num_rho = max(3, min(10, self.get_peer_count() + 1))
        for _ in range(num_rho):
            seed = random.randint(2, max(3, n - 1))
            subtasks.append({
                'algorithm': 'pollard_rho',
                'params': {
                    'n': n,
                    'seed': seed,
                    'max_iterations': POLLARD_MAX_ITER,
                },
            })

        return subtasks

    # --- Result aggregation and consensus ---

    def _try_aggregate(self, task_id: uuid.UUID):
        """
        Try to aggregate results for a task.

        If we have enough results, compute consensus and signal completion.
        """
        with self._tasks_lock:
            state = self._active_tasks.get(task_id)
        if state is None:
            return

        # Collect all factors from all subtask results
        all_factors = set()
        with state.lock:
            for subtask_idx, peer_results in state.results.items():
                for peer_id, factors in peer_results.items():
                    for f in factors:
                        if f > 1 and state.n % f == 0:
                            all_factors.add(f)

        if all_factors:
            # We have at least some factors — try to build complete factorization
            factors = self._build_complete_factorization(state.n, all_factors)
            if factors:
                state.final_factors = factors
                self._result_values[task_id] = factors
                event = self._result_events.get(task_id)
                if event:
                    event.set()

    def _build_complete_factorization(self, n: int,
                                       discovered: set[int]) -> list[int]:
        """
        Given discovered factors, try to build a complete prime factorization.

        Uses discovered factors to divide n, then factors any remaining
        cofactors locally.
        """
        factors = []
        remaining = n

        # Sort discovered factors and use them
        for f in sorted(discovered):
            while remaining % f == 0:
                # Check if f is prime (or at least doesn't have known subfactors)
                factors.append(f)
                remaining //= f

        if remaining > 1:
            # Factor the remaining part locally
            remaining_factors = factorization.full_factorization(remaining)
            factors.extend(remaining_factors)

        factors.sort()

        # Verify
        product = 1
        for f in factors:
            product *= f
        if product == n:
            return factors
        else:
            # Partial result — return what we have
            return factors

    def _aggregate_results(self, task_id: uuid.UUID, n: int) -> list[int]:
        """
        Final aggregation with consensus.

        Uses majority vote across redundant results for each subtask.
        """
        with self._tasks_lock:
            state = self._active_tasks.get(task_id)
        if state is None:
            return []

        # If we already have final factors, return them
        if state.final_factors:
            return state.final_factors

        # Gather all valid factors
        all_factors = set()
        with state.lock:
            for subtask_idx, peer_results in state.results.items():
                # Majority vote: count how many peers found each factor
                factor_votes: dict[int, int] = defaultdict(int)
                for peer_id, factors in peer_results.items():
                    for f in factors:
                        if f > 1 and n % f == 0:
                            factor_votes[f] += 1

                # Accept factors with at least 1 vote (since we verified n % f == 0)
                for f, votes in factor_votes.items():
                    all_factors.add(f)

        if all_factors:
            return self._build_complete_factorization(n, all_factors)

        # Fallback: factor locally
        logger.warning("No network results for task %s, factoring locally", task_id)
        return factorization.full_factorization(n)

    # --- Peer management ---

    def _get_peer(self, peer_id: bytes) -> PeerInfo | None:
        with self._peers_lock:
            return self._peers.get(peer_id)

    def _get_active_peers(self) -> list[PeerInfo]:
        """Get peers that are not blacklisted."""
        with self._peers_lock:
            return [
                p for p in self._peers.values()
                if not self._reputation.is_blacklisted(p.peer_id)
            ]

    # --- Gossip ---

    def _gossip_loop(self):
        """Periodically gossip with random peers."""
        while self._running:
            time.sleep(GOSSIP_INTERVAL)
            peers = self._get_active_peers()
            if not peers:
                # Try bootstrap peers again
                for addr in self._bootstrap:
                    self._send_hello(addr)
                continue

            # Pick a random peer to gossip with
            peer = random.choice(peers)
            self._send_peers((peer.host, peer.port))
