"""Tests for the binary protocol module."""

import unittest
import uuid

from gradatim import crypto
from gradatim import protocol


class TestSerializationHelpers(unittest.TestCase):

    def test_bigint_roundtrip(self):
        for value in [0, 1, 255, 256, 2**64, 2**128, 2**256 - 1]:
            encoded = protocol.encode_bigint(value)
            decoded, offset = protocol.decode_bigint(encoded, 0)
            self.assertEqual(decoded, value)
            self.assertEqual(offset, len(encoded))

    def test_string_roundtrip(self):
        for s in ["", "hello", "trial_division", "a" * 1000]:
            encoded = protocol.encode_string(s)
            decoded, offset = protocol.decode_string(encoded, 0)
            self.assertEqual(decoded, s)
            self.assertEqual(offset, len(encoded))

    def test_uuid_roundtrip(self):
        uid = uuid.uuid4()
        encoded = protocol.encode_uuid(uid)
        self.assertEqual(len(encoded), 16)
        decoded, offset = protocol.decode_uuid(encoded, 0)
        self.assertEqual(decoded, uid)

    def test_address_roundtrip(self):
        encoded = protocol.encode_address("127.0.0.1", 9001)
        decoded, offset = protocol.decode_address(encoded, 0)
        self.assertEqual(decoded, ("127.0.0.1", 9001))

    def test_bytes_roundtrip(self):
        data = b"\x01\x02\x03\x04"
        encoded = protocol.encode_bytes(data)
        decoded, offset = protocol.decode_bytes(encoded, 0)
        self.assertEqual(decoded, data)


class TestMessageSerialization(unittest.TestCase):

    def setUp(self):
        self.sk, self.pk = crypto.generate_keypair()
        self.sender_id = uuid.uuid4().bytes

    def test_message_roundtrip(self):
        payload = b"test payload data"
        msg = protocol.Message(
            msg_type=protocol.MSG_HELLO,
            sender_id=self.sender_id,
            payload=payload,
            nonce=42,
        )
        msg.sign(self.sk)

        data = msg.serialize()
        msg2 = protocol.Message.deserialize(data)

        self.assertEqual(msg2.version, protocol.PROTOCOL_VERSION)
        self.assertEqual(msg2.msg_type, protocol.MSG_HELLO)
        self.assertEqual(msg2.sender_id, self.sender_id)
        self.assertEqual(msg2.nonce, 42)
        self.assertEqual(msg2.payload, payload)
        self.assertTrue(msg2.verify_signature(self.pk))

    def test_signature_verification_fails_with_wrong_key(self):
        msg = protocol.Message(
            msg_type=protocol.MSG_ASSIGN,
            sender_id=self.sender_id,
            payload=b"data",
        )
        msg.sign(self.sk)
        _, wrong_pk = crypto.generate_keypair()
        data = msg.serialize()
        msg2 = protocol.Message.deserialize(data)
        self.assertFalse(msg2.verify_signature(wrong_pk))


class TestPayloadBuilders(unittest.TestCase):

    def test_hello_payload(self):
        sk, pk = crypto.generate_keypair()
        payload = protocol.build_hello_payload(
            ['trial_division', 'pollard_rho'], pk, 9001
        )
        parsed = protocol.parse_hello_payload(payload)
        self.assertEqual(parsed['capabilities'], ['trial_division', 'pollard_rho'])
        self.assertEqual(parsed['public_key'], pk)
        self.assertEqual(parsed['listen_port'], 9001)

    def test_peers_payload(self):
        peers = [
            (uuid.uuid4().bytes, "10.0.0.1", 9001),
            (uuid.uuid4().bytes, "10.0.0.2", 9002),
        ]
        payload = protocol.build_peers_payload(peers)
        parsed = protocol.parse_peers_payload(payload)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0][1], "10.0.0.1")
        self.assertEqual(parsed[0][2], 9001)

    def test_assign_payload(self):
        task_id = uuid.uuid4()
        params = {'n': 5959, 'start': 2, 'end': 78}
        payload = protocol.build_assign_payload(task_id, 'trial_division', params)
        parsed = protocol.parse_assign_payload(payload)
        self.assertEqual(parsed['task_id'], task_id)
        self.assertEqual(parsed['algorithm'], 'trial_division')
        self.assertEqual(parsed['params'], params)

    def test_result_payload(self):
        task_id = uuid.uuid4()
        factors = [59, 101]
        payload = protocol.build_result_payload(task_id, factors, 'complete')
        parsed = protocol.parse_result_payload(payload)
        self.assertEqual(parsed['task_id'], task_id)
        self.assertEqual(parsed['factors'], factors)
        self.assertEqual(parsed['status'], 'complete')

    def test_verify_payload(self):
        task_id = uuid.uuid4()
        payload = protocol.build_verify_payload(task_id, 5959, [59, 101])
        parsed = protocol.parse_verify_payload(payload)
        self.assertEqual(parsed['task_id'], task_id)
        self.assertEqual(parsed['n'], 5959)
        self.assertEqual(parsed['claimed_factors'], [59, 101])


if __name__ == "__main__":
    unittest.main()
