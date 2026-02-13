"""
Custom binary protocol for agent-to-agent communication.

Message layout:
  [Version: 1B][Type: 1B][SenderID: 16B][Timestamp: 8B][Nonce: 8B]
  [PayloadLen: 4B][Payload: variable][SigLen: 2B][Signature: variable]

Total header before payload: 1 + 1 + 16 + 8 + 8 + 4 = 38 bytes.

All integers are big-endian. Bigints and strings are length-prefixed (4-byte len).
"""

import struct
import time
import uuid

from . import crypto

PROTOCOL_VERSION = 1

# Message types
MSG_HELLO = 0x01    # Announce self: capabilities + public key
MSG_PEERS = 0x02    # Share peer list
MSG_ASSIGN = 0x03   # Assign a subtask
MSG_RESULT = 0x04   # Return a result
MSG_VERIFY = 0x05   # Verification/consensus request

HEADER_FMT = '>BB16sQQ I'  # version, type, sender_id, timestamp, nonce, payload_len
HEADER_SIZE = struct.calcsize(HEADER_FMT)  # 38 bytes

# Maximum message age before it's considered stale (seconds)
MAX_MESSAGE_AGE = 300

# Maximum payload size (1 MB)
MAX_PAYLOAD_SIZE = 1 * 1024 * 1024


class Message:
    """A protocol message with header, payload, and signature."""
    __slots__ = (
        'version', 'msg_type', 'sender_id', 'timestamp', 'nonce',
        'payload', 'signature_r', 'signature_s',
    )

    def __init__(self, msg_type: int, sender_id: bytes, payload: bytes,
                 nonce: int = 0, timestamp: int | None = None,
                 signature_r: int = 0, signature_s: int = 0):
        self.version = PROTOCOL_VERSION
        self.msg_type = msg_type
        self.sender_id = sender_id  # 16 bytes (UUID)
        self.timestamp = timestamp if timestamp is not None else int(time.time())
        self.nonce = nonce
        self.payload = payload
        self.signature_r = signature_r
        self.signature_s = signature_s

    def header_and_payload_bytes(self) -> bytes:
        """Serialize header + payload (the part that gets signed)."""
        header = struct.pack(
            HEADER_FMT,
            self.version, self.msg_type, self.sender_id,
            self.timestamp, self.nonce, len(self.payload),
        )
        return header + self.payload

    def sign(self, private_key: int):
        """Sign this message with the sender's private key."""
        data = self.header_and_payload_bytes()
        self.signature_r, self.signature_s = crypto.sign(private_key, data)

    def verify_signature(self, public_key: crypto.Point) -> bool:
        """Verify this message's signature against a public key."""
        data = self.header_and_payload_bytes()
        return crypto.verify(public_key, data, self.signature_r, self.signature_s)

    def serialize(self) -> bytes:
        """Serialize entire message to bytes for transmission."""
        body = self.header_and_payload_bytes()
        sig_bytes = crypto.signature_to_bytes(self.signature_r, self.signature_s)
        sig_len = len(sig_bytes)
        return body + struct.pack('>H', sig_len) + sig_bytes

    @classmethod
    def deserialize(cls, data: bytes) -> 'Message':
        """Deserialize a message from raw bytes."""
        if len(data) < HEADER_SIZE:
            raise ValueError(f"Message too short: {len(data)} < {HEADER_SIZE}")

        version, msg_type, sender_id, timestamp, nonce, payload_len = struct.unpack(
            HEADER_FMT, data[:HEADER_SIZE]
        )

        if version != PROTOCOL_VERSION:
            raise ValueError(f"Unknown protocol version: {version}")
        if payload_len > MAX_PAYLOAD_SIZE:
            raise ValueError(f"Payload too large: {payload_len}")

        offset = HEADER_SIZE
        if len(data) < offset + payload_len + 2:
            raise ValueError("Message truncated (payload)")

        payload = data[offset:offset + payload_len]
        offset += payload_len

        sig_len = struct.unpack('>H', data[offset:offset + 2])[0]
        offset += 2

        if len(data) < offset + sig_len:
            raise ValueError("Message truncated (signature)")

        sig_bytes = data[offset:offset + sig_len]
        r, s = crypto.signature_from_bytes(sig_bytes)

        msg = cls(
            msg_type=msg_type,
            sender_id=sender_id,
            payload=payload,
            nonce=nonce,
            timestamp=timestamp,
            signature_r=r,
            signature_s=s,
        )
        msg.version = version
        return msg

    def is_stale(self) -> bool:
        """Check if this message is too old."""
        return abs(time.time() - self.timestamp) > MAX_MESSAGE_AGE


# --- Payload serialization helpers ---

def encode_bigint(n: int) -> bytes:
    """Encode an arbitrary-size integer as length-prefixed big-endian bytes."""
    if n == 0:
        raw = b'\x00'
    elif n > 0:
        byte_len = (n.bit_length() + 7) // 8
        raw = n.to_bytes(byte_len, 'big')
    else:
        # Two's complement for negative
        byte_len = (n.bit_length() + 8) // 8
        raw = n.to_bytes(byte_len, 'big', signed=True)
    return struct.pack('>I', len(raw)) + raw


def decode_bigint(data: bytes, offset: int) -> tuple:
    """Decode a length-prefixed bigint. Returns (value, new_offset)."""
    if offset + 4 > len(data):
        raise ValueError("Truncated bigint length")
    length = struct.unpack('>I', data[offset:offset + 4])[0]
    offset += 4
    if offset + length > len(data):
        raise ValueError("Truncated bigint data")
    raw = data[offset:offset + length]
    value = int.from_bytes(raw, 'big')
    return value, offset + length


def encode_string(s: str) -> bytes:
    """Encode a string as length-prefixed UTF-8."""
    raw = s.encode('utf-8')
    return struct.pack('>I', len(raw)) + raw


def decode_string(data: bytes, offset: int) -> tuple:
    """Decode a length-prefixed string. Returns (string, new_offset)."""
    if offset + 4 > len(data):
        raise ValueError("Truncated string length")
    length = struct.unpack('>I', data[offset:offset + 4])[0]
    offset += 4
    if offset + length > len(data):
        raise ValueError("Truncated string data")
    s = data[offset:offset + length].decode('utf-8')
    return s, offset + length


def encode_bytes(b: bytes) -> bytes:
    """Encode raw bytes as length-prefixed."""
    return struct.pack('>I', len(b)) + b


def decode_bytes(data: bytes, offset: int) -> tuple:
    """Decode length-prefixed bytes. Returns (bytes, new_offset)."""
    if offset + 4 > len(data):
        raise ValueError("Truncated bytes length")
    length = struct.unpack('>I', data[offset:offset + 4])[0]
    offset += 4
    if offset + length > len(data):
        raise ValueError("Truncated bytes data")
    return data[offset:offset + length], offset + length


def encode_uuid(uid: uuid.UUID) -> bytes:
    """Encode a UUID as 16 bytes."""
    return uid.bytes


def decode_uuid(data: bytes, offset: int) -> tuple:
    """Decode 16-byte UUID. Returns (UUID, new_offset)."""
    if offset + 16 > len(data):
        raise ValueError("Truncated UUID")
    return uuid.UUID(bytes=data[offset:offset + 16]), offset + 16


def encode_address(host: str, port: int) -> bytes:
    """Encode a network address."""
    return encode_string(host) + struct.pack('>H', port)


def decode_address(data: bytes, offset: int) -> tuple:
    """Decode a network address. Returns ((host, port), new_offset)."""
    host, offset = decode_string(data, offset)
    if offset + 2 > len(data):
        raise ValueError("Truncated address port")
    port = struct.unpack('>H', data[offset:offset + 2])[0]
    return (host, port), offset + 2


# --- Payload builders for each message type ---

def build_hello_payload(capabilities: list[str], public_key: crypto.Point,
                        listen_port: int) -> bytes:
    """Build HELLO payload: capabilities list + public key + listen port."""
    buf = struct.pack('>H', len(capabilities))
    for cap in capabilities:
        buf += encode_string(cap)
    buf += encode_bytes(crypto.public_key_to_bytes(public_key))
    buf += struct.pack('>H', listen_port)
    return buf


def parse_hello_payload(data: bytes) -> dict:
    """Parse HELLO payload. Returns dict with capabilities, public_key, listen_port."""
    offset = 0
    cap_count = struct.unpack('>H', data[offset:offset + 2])[0]
    offset += 2
    capabilities = []
    for _ in range(cap_count):
        cap, offset = decode_string(data, offset)
        capabilities.append(cap)
    pk_bytes, offset = decode_bytes(data, offset)
    public_key = crypto.public_key_from_bytes(pk_bytes)
    listen_port = struct.unpack('>H', data[offset:offset + 2])[0]
    return {
        'capabilities': capabilities,
        'public_key': public_key,
        'listen_port': listen_port,
    }


def build_peers_payload(peers: list[tuple]) -> bytes:
    """
    Build PEERS payload: list of (uuid_bytes, host, port).
    """
    buf = struct.pack('>H', len(peers))
    for peer_id_bytes, host, port in peers:
        buf += peer_id_bytes  # 16 bytes
        buf += encode_address(host, port)
    return buf


def parse_peers_payload(data: bytes) -> list:
    """Parse PEERS payload. Returns list of (uuid_bytes, host, port)."""
    offset = 0
    count = struct.unpack('>H', data[offset:offset + 2])[0]
    offset += 2
    peers = []
    for _ in range(count):
        peer_id_bytes = data[offset:offset + 16]
        offset += 16
        (host, port), offset = decode_address(data, offset)
        peers.append((peer_id_bytes, host, port))
    return peers


def build_assign_payload(task_id: uuid.UUID, algorithm: str,
                         params: dict) -> bytes:
    """
    Build ASSIGN payload for a subtask.

    params keys depend on algorithm:
      - 'trial_division': {'n': int, 'start': int, 'end': int}
      - 'pollard_rho': {'n': int, 'seed': int, 'max_iterations': int}
    """
    buf = encode_uuid(task_id)
    buf += encode_string(algorithm)
    # Encode params as key-value pairs of bigints
    buf += struct.pack('>H', len(params))
    for key, value in params.items():
        buf += encode_string(key)
        buf += encode_bigint(value)
    return buf


def parse_assign_payload(data: bytes) -> dict:
    """Parse ASSIGN payload. Returns dict with task_id, algorithm, params."""
    offset = 0
    task_id, offset = decode_uuid(data, offset)
    algorithm, offset = decode_string(data, offset)
    param_count = struct.unpack('>H', data[offset:offset + 2])[0]
    offset += 2
    params = {}
    for _ in range(param_count):
        key, offset = decode_string(data, offset)
        value, offset = decode_bigint(data, offset)
        params[key] = value
    return {'task_id': task_id, 'algorithm': algorithm, 'params': params}


def build_result_payload(task_id: uuid.UUID, factors: list[int],
                         status: str = 'complete') -> bytes:
    """Build RESULT payload: task_id + list of discovered factors + status."""
    buf = encode_uuid(task_id)
    buf += encode_string(status)
    buf += struct.pack('>H', len(factors))
    for f in factors:
        buf += encode_bigint(f)
    return buf


def parse_result_payload(data: bytes) -> dict:
    """Parse RESULT payload. Returns dict with task_id, factors, status."""
    offset = 0
    task_id, offset = decode_uuid(data, offset)
    status, offset = decode_string(data, offset)
    count = struct.unpack('>H', data[offset:offset + 2])[0]
    offset += 2
    factors = []
    for _ in range(count):
        f, offset = decode_bigint(data, offset)
        factors.append(f)
    return {'task_id': task_id, 'factors': factors, 'status': status}


def build_verify_payload(task_id: uuid.UUID, n: int,
                         claimed_factors: list[int]) -> bytes:
    """Build VERIFY payload for consensus check."""
    buf = encode_uuid(task_id)
    buf += encode_bigint(n)
    buf += struct.pack('>H', len(claimed_factors))
    for f in claimed_factors:
        buf += encode_bigint(f)
    return buf


def parse_verify_payload(data: bytes) -> dict:
    """Parse VERIFY payload."""
    offset = 0
    task_id, offset = decode_uuid(data, offset)
    n, offset = decode_bigint(data, offset)
    count = struct.unpack('>H', data[offset:offset + 2])[0]
    offset += 2
    factors = []
    for _ in range(count):
        f, offset = decode_bigint(data, offset)
        factors.append(f)
    return {'task_id': task_id, 'n': n, 'claimed_factors': factors}
