import hashlib
import unittest

from web3 import Web3

from server.blockchain import content_commitment, next_chunk_commitment, split_bytes


class OnChainChunkingTests(unittest.TestCase):
    def test_split_bytes_preserves_exact_binary_content(self):
        content = "隐私政策🙂".encode("utf-8") + bytes(range(64))

        chunks = split_bytes(content, 7)

        self.assertGreater(len(chunks), 1)
        self.assertEqual(b"".join(chunks), content)
        self.assertTrue(all(0 < len(chunk) <= 7 for chunk in chunks))

    def test_commitment_is_order_and_boundary_sensitive(self):
        chunks = [b"first", b"second", b"third"]
        commitment = content_commitment(chunks)

        self.assertEqual(len(commitment), 32)
        self.assertNotEqual(commitment, content_commitment(list(reversed(chunks))))
        self.assertNotEqual(commitment, content_commitment([b"firstsecond", b"third"]))

    def test_commitment_matches_solidity_packed_formula(self):
        chunk = b"policy chunk"
        expected = Web3.solidity_keccak(
            ["bytes32", "uint32", "uint64", "bytes32"],
            [bytes(32), 0, len(chunk), hashlib.sha256(chunk).digest()],
        )

        self.assertEqual(next_chunk_commitment(bytes(32), 0, chunk), bytes(expected))

    def test_invalid_chunk_sizes_are_rejected(self):
        with self.assertRaises(ValueError):
            split_bytes(b"content", 0)
        with self.assertRaises(ValueError):
            next_chunk_commitment(bytes(32), 0, b"")


if __name__ == "__main__":
    unittest.main()
