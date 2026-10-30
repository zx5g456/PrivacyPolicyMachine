import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import hre from "hardhat";
import { BrowserProvider, ContractFactory, concat, sha256 } from "ethers";

const artifact = JSON.parse(
  await readFile(
    new URL(
      "../artifacts/contracts/TrustedPolicyRegistry.sol/TrustedPolicyRegistry.json",
      import.meta.url,
    ),
    "utf8",
  ),
);
const connection = await hre.network.create();
const provider = new BrowserProvider(connection.provider);
const owner = await provider.getSigner(0);
const unauthorized = await provider.getSigner(1);
const registry = await new ContractFactory(artifact.abi, artifact.bytecode, owner).deploy(
  await owner.getAddress(),
);
await registry.waitForDeployment();

const document = Buffer.from("integration-test privacy policy", "utf8");
const metadata = Buffer.from('{"test":true}', "utf8");
const manifest = {
  documentHash: sha256(document),
  metadataHash: sha256(metadata),
  documentSize: document.length,
  metadataSize: metadata.length,
  publisherEntity: "integration-test-publisher",
  serviceName: "integration-test-service",
  policyVersion: "integration-test-version",
  effectiveDate: "2026-09-21",
};
const recordKey = await registry.getRecordKey(
  manifest.publisherEntity,
  manifest.serviceName,
  manifest.policyVersion,
);

await assert.rejects(
  registry.connect(unauthorized).beginPolicyRegistration(manifest),
  /authorized publisher owner|execution reverted/i,
);
await (await registry.setPublisherOwner(manifest.publisherEntity, await owner.getAddress())).wait();
await (await registry.beginPolicyRegistration(manifest)).wait();
await (await registry.appendDocumentChunk(recordKey, 0, document)).wait();
await (await registry.appendMetadataChunk(recordKey, 0, metadata)).wait();
await (await registry.finalizePolicyRegistration(recordKey)).wait();
const registered = await registry.readRecordByKey(recordKey);
assert.equal(await registry.registeredDocumentCommitments(registered.documentChunkCommitment), true);
const duplicateKey = await registry.getRecordKey(
  manifest.publisherEntity,
  manifest.serviceName,
  "duplicate-document",
);
await (await registry.beginPolicyRegistration({ ...manifest, policyVersion: "duplicate-document" })).wait();
await (await registry.appendDocumentChunk(duplicateKey, 0, document)).wait();
await (await registry.appendMetadataChunk(duplicateKey, 0, metadata)).wait();
await assert.rejects(
  registry.finalizePolicyRegistration(duplicateKey),
  /Document content commitment already registered|execution reverted/i,
);
await (await registry.cancelPolicyRegistration(duplicateKey)).wait();

const bundle = Buffer.from("deterministic compliance bundle bytes", "utf8");
const complianceManifest = {
  bundleHash: sha256(bundle),
  sourceDocumentHash: sha256(document),
  pipelineVersionHash: sha256(Buffer.from("pipeline-v1", "utf8")),
  bundleSize: bundle.length,
};

await assert.rejects(
  registry.connect(unauthorized).beginComplianceUpload(recordKey, complianceManifest),
  /authorized compliance uploader|execution reverted/i,
);

await (await registry.beginComplianceUpload(recordKey, complianceManifest)).wait();
const split = Math.floor(bundle.length / 2);
await (await registry.appendComplianceChunk(recordKey, 0, bundle.subarray(0, split))).wait();
await (await registry.appendComplianceChunk(recordKey, 1, bundle.subarray(split))).wait();
await (await registry.finalizeComplianceUpload(recordKey)).wait();

assert.equal(await registry.hasComplianceResult(recordKey), true);
const result = await registry.readComplianceResult(recordKey);
assert.equal(result.bundleHash, complianceManifest.bundleHash);
assert.equal(result.sourceDocumentHash, complianceManifest.sourceDocumentHash);
assert.equal(Number(result.bundleSize), bundle.length);
assert.equal(Number(result.chunkCount), 2);
const restored = concat([
  await registry.readComplianceChunk(recordKey, 0),
  await registry.readComplianceChunk(recordKey, 1),
]);
assert.equal(sha256(restored), complianceManifest.bundleHash);

await assert.rejects(
  registry.beginComplianceUpload(recordKey, complianceManifest),
  /already exists|execution reverted/i,
);

console.log(`Compliance contract integration passed for ${recordKey}`);
await connection.close();
