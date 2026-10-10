#!/usr/bin/env node
// Independent, read-only auditor. This module imports no application or database code.
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { resolve, dirname, join } from "node:path";
import {
  AbiCoder,
  Contract,
  JsonRpcProvider,
  ZeroHash,
  concat,
  getBytes,
  keccak256,
  sha256,
  solidityPackedKeccak256,
} from "ethers";

const artifactPath = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "../artifacts/contracts/TrustedPolicyRegistry.sol/TrustedPolicyRegistry.json",
);

function remember(checks, name, passed) {
  checks[name] = Boolean(passed);
}

async function recoverContent(registry, recordKey, kind, count) {
  const chunks = [];
  let commitment = ZeroHash;
  for (let index = 0; index < count; index += 1) {
    const raw = kind === "document"
      ? await registry.readDocumentChunk(recordKey, index)
      : await registry.readMetadataChunk(recordKey, index);
    const chunk = getBytes(raw);
    chunks.push(chunk);
    commitment = solidityPackedKeccak256(
      ["bytes32", "uint32", "uint64", "bytes32"],
      [commitment, index, chunk.length, sha256(chunk)],
    );
  }
  return { bytes: Buffer.from(getBytes(concat(chunks))), commitment, chunks: chunks.length };
}

async function auditRecord(registry, provider, recordKey, record) {
  const checks = {};
  const expectedKey = keccak256(AbiCoder.defaultAbiCoder().encode(
    ["string", "string", "string"],
    [record.publisherEntity, record.serviceName, record.policyVersion],
  ));
  remember(checks, "recordKey", expectedKey === recordKey);
  const document = await recoverContent(
    registry, recordKey, "document", Number(record.documentChunkCount),
  );
  const metadata = await recoverContent(
    registry, recordKey, "metadata", Number(record.metadataChunkCount),
  );
  remember(checks, "documentHash", sha256(document.bytes) === record.documentHash);
  remember(checks, "metadataHash", sha256(metadata.bytes) === record.metadataHash);
  remember(checks, "documentSize", document.bytes.length === Number(record.documentSize));
  remember(checks, "metadataSize", metadata.bytes.length === Number(record.metadataSize));
  remember(checks, "documentChunkCount", document.chunks === Number(record.documentChunkCount));
  remember(checks, "metadataChunkCount", metadata.chunks === Number(record.metadataChunkCount));
  remember(checks, "documentCommitment", document.commitment === record.documentChunkCommitment);
  remember(checks, "metadataCommitment", metadata.commitment === record.metadataChunkCommitment);

  let parsedMetadata;
  try {
    parsedMetadata = JSON.parse(metadata.bytes.toString("utf8"));
  } catch {
    parsedMetadata = null;
  }
  remember(checks, "metadataJson", parsedMetadata !== null && typeof parsedMetadata === "object");

  const logs = await registry.queryFilter(
    registry.filters.TrustedPolicyRecordRegistered(recordKey), 0, "latest",
  );
  remember(checks, "oneFinalizationEvent", logs.length === 1);
  let finalizationTxHash = null;
  if (logs.length === 1) {
    const event = logs[0];
    finalizationTxHash = event.transactionHash;
    const [transaction, receipt] = await Promise.all([
      provider.getTransaction(finalizationTxHash),
      provider.getTransactionReceipt(finalizationTxHash),
    ]);
    let decoded;
    try {
      decoded = registry.interface.parseTransaction({ data: transaction?.data ?? "0x" });
    } catch {
      decoded = null;
    }
    remember(checks, "finalizationSucceeded", receipt?.status === 1);
    remember(checks, "finalizationTargetsRegistry",
      transaction?.to?.toLowerCase() === String(registry.target).toLowerCase());
    remember(checks, "finalizationCall",
      decoded?.name === "finalizePolicyRegistration" && decoded.args[0] === recordKey);
    remember(checks, "registrant", transaction?.from?.toLowerCase() === record.registrant.toLowerCase());
    remember(checks, "eventRecordKey", event.args.recordKey === recordKey);
    remember(checks, "eventDocumentHash", event.args.documentHash === record.documentHash);
    remember(checks, "eventMetadataHash", event.args.metadataHash === record.metadataHash);
    remember(checks, "eventPreviousKey", event.args.previousRecordKey === record.previousRecordKey);
    remember(checks, "eventTimestamp", Number(event.args.registeredAt) === Number(record.registeredAt));
  }
  return {
    recordKey,
    policyVersion: record.policyVersion,
    publisherEntity: record.publisherEntity,
    serviceName: record.serviceName,
    effectiveDate: record.effectiveDate,
    registrant: record.registrant,
    registeredAt: Number(record.registeredAt),
    previousRecordKey: record.previousRecordKey,
    hasPreviousReference: record.hasPreviousReference,
    documentHash: record.documentHash,
    metadataHash: record.metadataHash,
    finalizationTxHash,
    rawFileBase64: document.bytes.toString("base64"),
    metadataJsonBase64: metadata.bytes.toString("base64"),
    checks,
    valid: Object.values(checks).every(Boolean),
  };
}

export async function auditFamily(registry, provider, publisherEntity, serviceName) {
  const errors = [];
  const records = [];
  let indexedKeys = [];
  try {
    indexedKeys = [...await registry.getPolicyRecordKeys(publisherEntity, serviceName)];
    if (indexedKeys.length === 0) throw new Error("No registered versions found");
    let cursor = indexedKeys.at(-1);
    const visited = new Set();
    while (cursor !== ZeroHash) {
      if (visited.has(cursor)) throw new Error(`Version cycle at ${cursor}`);
      visited.add(cursor);
      const record = await registry.readRecordByKey(cursor);
      const audited = await auditRecord(registry, provider, cursor, record);
      remember(audited.checks, "family",
        record.publisherEntity === publisherEntity && record.serviceName === serviceName);
      remember(audited.checks, "previousFlag",
        Boolean(record.hasPreviousReference) === (record.previousRecordKey !== ZeroHash));
      audited.valid = Object.values(audited.checks).every(Boolean);
      records.push(audited);
      cursor = record.previousRecordKey;
      if (records.length > indexedKeys.length) throw new Error("Version chain exceeds public index");
    }
    records.reverse();
    if (records.length !== indexedKeys.length ||
        records.some((record, index) => record.recordKey !== indexedKeys[index])) {
      errors.push("Predecessor chain does not match the public version index");
    }
    for (let index = 0; index < records.length; index += 1) {
      const expectedPrevious = index === 0 ? ZeroHash : records[index - 1].recordKey;
      if (records[index].previousRecordKey !== expectedPrevious) {
        errors.push(`Invalid predecessor for ${records[index].recordKey}`);
      }
    }
  } catch (error) {
    errors.push(error instanceof Error ? error.message : String(error));
  }
  return {
    publisherEntity,
    serviceName,
    indexedVersionCount: indexedKeys.length,
    records,
    errors,
    valid: errors.length === 0 && records.length === indexedKeys.length &&
      records.every((record) => record.valid),
  };
}

function argument(name) {
  const index = process.argv.indexOf(name);
  if (index < 0 || index + 1 >= process.argv.length) throw new Error(`${name} is required`);
  return process.argv[index + 1];
}

async function main() {
  const rpcUrl = argument("--rpc-url");
  const contractAddress = argument("--contract-address");
  const publisherEntity = argument("--publisher");
  const serviceName = argument("--service");
  const selectedArtifact = process.argv.includes("--artifact") ? argument("--artifact") : artifactPath;
  const artifact = JSON.parse(await readFile(selectedArtifact, "utf8"));
  const provider = new JsonRpcProvider(rpcUrl);
  try {
    if (await provider.getCode(contractAddress) === "0x") throw new Error("Registry not deployed");
    const registry = new Contract(contractAddress, artifact.abi, provider);
    const result = await auditFamily(registry, provider, publisherEntity, serviceName);
    if (process.argv.includes("--output-dir")) {
      const outputDir = resolve(argument("--output-dir"));
      await mkdir(outputDir, { recursive: true });
      for (const record of result.records) {
        await writeFile(join(outputDir, `${record.recordKey}-policy.bin`),
          Buffer.from(record.rawFileBase64, "base64"));
        await writeFile(join(outputDir, `${record.recordKey}-metadata.json`),
          Buffer.from(record.metadataJsonBase64, "base64"));
      }
    }
    console.log(JSON.stringify(result, null, 2));
    if (!result.valid) process.exitCode = 1;
  } finally {
    provider.destroy();
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  });
}
