import tempfile
import unittest
from pathlib import Path

from server.compliance_bundle import (
    BUNDLE_FILENAME,
    COMPLIANCE_FILE_TYPES,
    MANIFEST_FILENAME,
    build_compliance_bundle,
    read_compliance_bundle,
    read_local_compliance_bundle,
    restore_compliance_bundle,
    write_compliance_bundle,
)


RECORD_KEY = "0x" + "11" * 32
DOCUMENT_HASH = "0x" + "22" * 32


class ComplianceBundleTests(unittest.TestCase):
    def setUp(self):
        self.files = {
            name: f"content for {name}\n".encode("utf-8")
            for name in COMPLIANCE_FILE_TYPES
        }

    def test_bundle_is_deterministic_and_preserves_exact_files(self):
        first = build_compliance_bundle(
            self.files,
            record_key=RECORD_KEY,
            source_document_hash=DOCUMENT_HASH,
            model="gpt-test",
            p3_mode="yes",
            pipeline_version="pipeline-test",
        )
        second = build_compliance_bundle(
            self.files,
            record_key=RECORD_KEY,
            source_document_hash=DOCUMENT_HASH,
            model="gpt-test",
            p3_mode="yes",
            pipeline_version="pipeline-test",
        )

        self.assertEqual(first.data, second.data)
        self.assertEqual(first.manifest["bundleHash"], second.manifest["bundleHash"])
        self.assertEqual(read_compliance_bundle(first.data).files, self.files)

    def test_local_bundle_validation_rejects_a_different_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            for name, content in self.files.items():
                (output_dir / name).write_bytes(content)
            write_compliance_bundle(
                output_dir,
                record_key=RECORD_KEY,
                source_document_hash=DOCUMENT_HASH,
                model="gpt-test",
                p3_mode="no",
                pipeline_version="pipeline-test",
            )

            self.assertTrue((output_dir / BUNDLE_FILENAME).is_file())
            self.assertTrue((output_dir / MANIFEST_FILENAME).is_file())
            self.assertIsNotNone(
                read_local_compliance_bundle(
                    output_dir,
                    record_key=RECORD_KEY,
                    source_document_hash=DOCUMENT_HASH,
                )
            )
            self.assertIsNone(
                read_local_compliance_bundle(
                    output_dir,
                    record_key="0x" + "33" * 32,
                    source_document_hash=DOCUMENT_HASH,
                )
            )

    def test_restore_recreates_all_local_files(self):
        bundle = build_compliance_bundle(
            self.files,
            record_key=RECORD_KEY,
            source_document_hash=DOCUMENT_HASH,
            model="gpt-test",
            p3_mode="yes",
            pipeline_version="pipeline-test",
        )
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            restored = restore_compliance_bundle(output_dir, bundle.data)

            self.assertEqual(restored.manifest, bundle.manifest)
            for name, content in self.files.items():
                self.assertEqual((output_dir / name).read_bytes(), content)


if __name__ == "__main__":
    unittest.main()
