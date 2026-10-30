import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import hre from "hardhat";
import { BrowserProvider, ContractFactory, sha256 } from "ethers";

const artifact = JSON.parse(
  await readFile(
    process.env.REGISTRY_ARTIFACT ??
      new URL("../artifacts/contracts/TrustedPolicyRegistry.sol/TrustedPolicyRegistry.json", import.meta.url),
    "utf8",
  ),
);
const connection = await hre.network.create();

try {
  const provider = new BrowserProvider(connection.provider);
  const owner = await provider.getSigner(0);
  const developer = await provider.getSigner(1);
  const registry = await new ContractFactory(artifact.abi, artifact.bytecode, owner).deploy(
    await owner.getAddress(),
  );
  await registry.waitForDeployment();
  await (await registry.setPublisherOwner("publisher", await developer.getAddress())).wait();

  const realDocument = Buffer.from("the actual privacy policy", "utf8");
  const differentDocument = Buffer.from("some unrelated policy bytes", "utf8");
  const metadata = Buffer.from("{}", "utf8");
  const claimedHash = sha256(realDocument);
  const baseManifest = {
    documentHash: claimedHash,
    metadataHash: sha256(metadata),
    metadataSize: metadata.length,
    publisherEntity: "publisher",
    serviceName: "service",
    effectiveDate: "",
  };

  async function upload(version, document, documentHash) {
    const recordKey = await registry.getRecordKey("publisher", "service", version);
    const manifest = {
      ...baseManifest,
      documentHash,
      documentSize: document.length,
      policyVersion: version,
    };
    await (await registry.connect(developer).beginPolicyRegistration(manifest)).wait();
    await (await registry.connect(developer).appendDocumentChunk(recordKey, 0, document)).wait();
    await (await registry.connect(developer).appendMetadataChunk(recordKey, 0, metadata)).wait();
    return recordKey;
  }

  const spoofedKey = await upload("spoofed-claim", differentDocument, claimedHash);
  await (await registry.connect(developer).finalizePolicyRegistration(spoofedKey)).wait();

  const genuineKey = await upload("genuine", realDocument, claimedHash);
  await (await registry.connect(developer).finalizePolicyRegistration(genuineKey)).wait();
  const spoofed = await registry.readRecordByKey(spoofedKey);
  const genuine = await registry.readRecordByKey(genuineKey);
  assert.equal(spoofed.documentHash, genuine.documentHash);
  assert.notEqual(spoofed.documentChunkCommitment, genuine.documentChunkCommitment);
  assert.equal(await registry.registeredDocumentCommitments(genuine.documentChunkCommitment), true);

  const duplicateKey = await upload("duplicate-content", realDocument, sha256(differentDocument));
  await assert.rejects(
    registry.connect(developer).finalizePolicyRegistration(duplicateKey),
    /Document content commitment already registered|execution reverted/i,
  );
  await (await registry.connect(developer).cancelPolicyRegistration(duplicateKey)).wait();
  assert.equal(await registry.hasRecord(duplicateKey), false);

  console.log("Registry commitment deduplication passed");
} finally {
  await connection.close();
}
