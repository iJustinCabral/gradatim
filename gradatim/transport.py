"""
Network transport layer for agent communication.

Uses UDP for primary message exchange (lightweight, fast).
Handles sending and receiving of protocol messages with size limits.
"""

import socket
import threading
import logging

from . import protocol

logger = logging.getLogger(__name__)

# UDP max practical payload (~64KB minus headers)
MAX_UDP_SIZE = 65507


class UDPTransport:
    """
    UDP-based transport for sending and receiving protocol messages.

    Binds to a local port and provides send/receive capabilities.
    Incoming messages are dispatched to a callback function.
    """

    def __init__(self, host: str, port: int, on_message_received):
        """
        Args:
            host: Local bind address (e.g. '127.0.0.1' or '0.0.0.0').
            port: Local bind port.
            on_message_received: Callback(message: Message, addr: tuple).
        """
        self.host = host
        self.port = port
        self._on_message = on_message_received
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._running = False
        self._listen_thread = None

    def start(self):
        """Bind socket and start the listener thread."""
        self._sock.bind((self.host, self.port))
        self._sock.settimeout(1.0)  # Allow periodic checks for shutdown
        self._running = True
        self._listen_thread = threading.Thread(
            target=self._listen_loop, daemon=True, name=f"udp-{self.port}"
        )
        self._listen_thread.start()
        logger.info("Transport listening on %s:%d", self.host, self.port)

    def stop(self):
        """Stop the listener and close the socket."""
        self._running = False
        if self._listen_thread:
            self._listen_thread.join(timeout=3.0)
        self._sock.close()
        logger.info("Transport stopped on port %d", self.port)

    def send(self, message: protocol.Message, addr: tuple):
        """
        Serialize and send a message to addr (host, port).

        Raises ValueError if serialized message exceeds UDP limit.
        """
        data = message.serialize()
        if len(data) > MAX_UDP_SIZE:
            raise ValueError(
                f"Message too large for UDP: {len(data)} > {MAX_UDP_SIZE}"
            )
        self._sock.sendto(data, addr)

    def _listen_loop(self):
        """Receive loop running in a background thread."""
        while self._running:
            try:
                data, addr = self._sock.recvfrom(MAX_UDP_SIZE)
            except socket.timeout:
                continue
            except OSError:
                if self._running:
                    logger.exception("Socket error in listen loop")
                break

            try:
                msg = protocol.Message.deserialize(data)
            except (ValueError, struct.error) as e:
                logger.debug("Dropped malformed message from %s: %s", addr, e)
                continue

            try:
                self._on_message(msg, addr)
            except Exception:
                logger.exception("Error in message handler for %s", addr)


# Needed for struct import in the except clause above
import struct  # noqa: E402
