import { spawn } from "node:child_process";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  Contract,
  FetchRequest,
  JsonRpcProvider,
  Wallet,
  getAddress,
  getBytes,
  keccak256,
  sha256,
  solidityPackedKeccak256,
} from "ethers";
import {
  BASE_CHAIN_ID, assertBaseChainId, loadBaseEnv, required,
} from "../config/load-base-env.js";
import { loadState } from "./listener-state.js";

await loadBaseEnv({ omit: ["BASE_DEPLOYER_PRIVATE_KEY"] });
assertBaseChainId();
const RPC_URL = required("RPC_URL");
const CONTRACT_ADDRESS = getAddress(required("CONTRACT_ADDRESS"));

const registryAbi = [
  "event TrustedPolicyRecordRegistered(bytes32 indexed recordKey, bytes32 indexed documentHash, bytes32 indexed metadataHash, bytes32 previousRecordKey, address registrant, uint64 registeredAt)",
  "function readRecordByKey(bytes32 recordKey) view returns (tuple(bytes32 documentHash, bytes32 metadataHash, bytes32 documentChunkCommitment, bytes32 metadataChunkCommitment, uint64 documentSize, uint64 metadataSize, uint32 documentChunkCount, uint32 metadataChunkCount, string publisherEntity, string serviceName, string policyVersion, string effectiveDate, address registrant, uint64 registeredAt, bytes32 previousRecordKey, bool hasPreviousReference) record)",
  "function readDocumentChunk(bytes32 recordKey, uint32 chunkIndex) view returns (bytes)",
  "function readMetadataChunk(bytes32 recordKey, uint32 chunkIndex) view returns (bytes)",
  "event ComplianceResultRegistered(bytes32 indexed recordKey, bytes32 indexed bundleHash, address indexed submitter, uint64 registeredAt)",
  "function complianceUploaders(address uploader) view returns (bool)",
  "function hasComplianceResult(bytes32 recordKey) view returns (bool)",
  "function hasPendingComplianceUpload(bytes32 recordKey) view returns (bool)",
  "function beginComplianceUpload(bytes32 recordKey, tuple(bytes32 bundleHash, bytes32 sourceDocumentHash, bytes32 pipelineVersionHash, uint64 bundleSize) manifest)",
  "function appendComplianceChunk(bytes32 recordKey, uint32 chunkIndex, bytes chunk)",
  "function finalizeComplianceUpload(bytes32 recordKey)",
  "function readComplianceUploadProgress(bytes32 recordKey) view returns (tuple(bytes32 bundleHash, bytes32 sourceDocumentHash, bytes32 pipelineVersionHash, bytes32 chunkCommitment, uint64 bundleSize, uint64 bytesStored, uint32 chunkCount, address submitter, bool active) pending)",
  "function readComplianceResult(bytes32 recordKey) view returns (tuple(bytes32 bundleHash, bytes32 sourceDocumentHash, bytes32 pipelineVersionHash, bytes32 chunkCommitment, uint64 bundleSize, uint32 chunkCount, address submitter, uint64 registeredAt) result)",
  "function readComplianceChunk(bytes32 recordKey, uint32 chunkIndex) view returns (bytes)",
  "function MAX_CHUNK_BYTES() view returns (uint256)",
];

const request = new FetchRequest(RPC_URL);
request.timeout = 30_000;
const provider = new JsonRpcProvider(request, undefined, { batchMaxCount: 1 });
const registry = new Contract(CONTRACT_ADDRESS, registryAbi, provider);
let complianceSigner;
try {
  complianceSigner = new Wallet(required("COMPLIANCE_PRIVATE_KEY"), provider);
} catch {
  throw new Error("COMPLIANCE_PRIVATE_KEY must be a valid private key in config/base-mainnet.env");
}
const complianceUploaderAddress = complianceSigner.address;
const complianceRegistry = registry.connect(complianceSigner);
const pollIntervalMs = positiveInteger("POLL_INTERVAL_MS", 5_000);
const blockBatchSize = positiveInteger("BLOCK_BATCH_SIZE", 2_000);
const projectRoot = fileURLToPath(new URL("../", import.meta.url));
const complianceRoot = join(projectRoot, "compliance tool");
const complianceOutputRoot = join(
  resolve(process.env.COMPLIANCE_OUTPUT_DIR ?? join(projectRoot, "data", "compliance-results")),
  String(BASE_CHAIN_ID),
  CONTRACT_ADDRESS.toLowerCase(),
);
const pythonExecutable =
  process.env.COMPLIANCE_PYTHON_PATH ??
  join(projectRoot, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const complianceModel = process.env.COMPLIANCE_GPT_MODEL ?? "gpt-4o-mini";
const complianceHighRisk = process.env.COMPLIANCE_HIGH_RISK ?? "auto";
const complianceChunkBytes = positiveInteger("COMPLIANCE_CHUNK_BYTES", 8 * 1024);
const complianceMaxBundleBytes = positiveInteger(
  "COMPLIANCE_MAX_BUNDLE_BYTES",
  1024 * 1024,
);
if (complianceChunkBytes === 0 || complianceMaxBundleBytes === 0) {
  throw new Error("Compliance chunk and bundle byte limits must be positive");
}
let running = true;

class InvalidOnChainPolicyError extends Error {}
class ComplianceAnalysisError extends Error {}

function runComplianceTool(label, script, args, rawFile) {
  return new Promise((resolveRun, rejectRun) => {
    const child = spawn(pythonExecutable, [script, ...args], {
      cwd: complianceRoot,
      env: process.env,
      stdio: ["pipe", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";

    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });
    child.once("error", rejectRun);
    child.once("close", (code) => {
      if (code === 0) {
        if (stdout.trim()) console.log(`${label}: ${stdout.trim()}`);
        resolveRun();
        return;
      }
      const details = stderr.trim() || stdout.trim() || `exit ${code}`;
      rejectRun(new Error(`${label} failed: ${details}`));
    });
    child.stdin.end(rawFile);
  });
}

function equalHex(first, second) {
  return String(first).toLowerCase() === String(second).toLowerCase();
}

function complianceCommitment(chunks) {
  let commitment = `0x${"00".repeat(32)}`;
  chunks.forEach((chunk, index) => {
    commitment = solidityPackedKeccak256(
      ["bytes32", "uint32", "uint64", "bytes32"],
      [commitment, index, chunk.length, sha256(chunk)],
    );
  });
  return commitment;
}

async function readComplianceChunks(recordKey, chunkCount) {
  const chunks = [];
  for (let index = 0; index < chunkCount; index += 1) {
    chunks.push(Buffer.from(getBytes(await registry.readComplianceChunk(recordKey, index))));
  }
  return chunks;
}

function validateComplianceManifest(manifest, bundle, recordKey, documentHash) {
  const requiredHashes = [
    ["bundleHash", manifest.bundleHash],
    ["sourceDocumentHash", manifest.sourceDocumentHash],
    ["pipelineVersionHash", manifest.pipelineVersionHash],
  ];
  for (const [name, value] of requiredHashes) {
    if (!/^0x[0-9a-fA-F]{64}$/.test(value ?? "")) {
      throw new Error(`Compliance manifest ${name} is not a bytes32 hash`);
    }
  }
  if (!equalHex(manifest.recordKey, recordKey)) {
    throw new Error("Compliance manifest recordKey does not match the policy event");
  }
  if (!equalHex(manifest.sourceDocumentHash, documentHash)) {
    throw new Error("Compliance manifest source hash does not match the policy record");
  }
  if (Number(manifest.bundleSize) !== bundle.length) {
    throw new Error("Compliance manifest bundle size does not match the local bundle");
  }
  if (!equalHex(manifest.bundleHash, sha256(bundle))) {
    throw new Error("Compliance manifest bundle hash does not match the local bundle");
  }
  if (bundle.length > complianceMaxBundleBytes) {
    throw new Error(
      `Compliance bundle is ${bundle.length} bytes; configured maximum is ${complianceMaxBundleBytes}`,
    );
  }
}

function validateFinalizedCompliance(result, manifest) {
  const comparisons = {
    bundleHash: equalHex(result.bundleHash, manifest.bundleHash),
    sourceDocumentHash: equalHex(
      result.sourceDocumentHash,
      manifest.sourceDocumentHash,
    ),
    pipelineVersionHash: equalHex(
      result.pipelineVersionHash,
      manifest.pipelineVersionHash,
    ),
    bundleSize: Number(result.bundleSize) === Number(manifest.bundleSize),
  };
  const failures = Object.entries(comparisons)
    .filter(([, valid]) => !valid)
    .map(([name]) => name);
  if (failures.length) {
    throw new Error(
      `Finalized compliance result does not match the local bundle: ${failures.join(", ")}`,
    );
  }
}

function validatePendingCompliance(pending, manifest, chunks) {
  const stored = Buffer.concat(chunks);
  const comparisons = {
    bundleHash: equalHex(pending.bundleHash, manifest.bundleHash),
    sourceDocumentHash: equalHex(
      pending.sourceDocumentHash,
      manifest.sourceDocumentHash,
    ),
    pipelineVersionHash: equalHex(
      pending.pipelineVersionHash,
      manifest.pipelineVersionHash,
    ),
    bundleSize: Number(pending.bundleSize) === Number(manifest.bundleSize),
    bytesStored: Number(pending.bytesStored) === stored.length,
    chunkCount: Number(pending.chunkCount) === chunks.length,
    chunkCommitment: equalHex(
      pending.chunkCommitment,
      complianceCommitment(chunks),
    ),
    submitter:
      String(pending.submitter).toLowerCase() ===
      complianceUploaderAddress.toLowerCase(),
  };
  const failures = Object.entries(comparisons)
    .filter(([, valid]) => !valid)
    .map(([name]) => name);
  if (failures.length) {
    throw new Error(
      `Pending compliance upload does not match this request: ${failures.join(", ")}`,
    );
  }
  return stored;
}

async function storableComplianceChunk(recordKey, chunkIndex, remaining) {
  const contractLimit = Number(await registry.MAX_CHUNK_BYTES());
  let size = Math.min(complianceChunkBytes, contractLimit, remaining.length);
  let lastError;
  while (size > 0) {
    const chunk = remaining.subarray(0, size);
    try {
      const estimated = await complianceRegistry.appendComplianceChunk.estimateGas(
        recordKey,
        chunkIndex,
        chunk,
      );
      const latestBlock = await provider.getBlock("latest");
      if (estimated >= (latestBlock.gasLimit * 8n) / 10n) {
        throw new Error("estimated compliance chunk gas is too close to the block limit");
      }
      return chunk;
    } catch (error) {
      lastError = error;
      if (size === 1) break;
      size = Math.max(1, Math.floor(size / 2));
    }
  }
  throw new Error(
    `Unable to store compliance chunk ${chunkIndex}: ${lastError?.message ?? "unknown error"}`,
  );
}

async function sendComplianceTransaction(phase, transactionPromise, transactions) {
  const transaction = await transactionPromise;
  const receipt = await transaction.wait();
  if (!receipt || receipt.status !== 1) {
    throw new Error(`Compliance ${phase} transaction failed`);
  }
  transactions.push({
    phase,
    txHash: transaction.hash,
    blockNumber: receipt.blockNumber,
    gasUsed: receipt.gasUsed.toString(),
  });
  return receipt;
}

async function complianceRegistrationEvent(recordKey) {
  const deploymentBlock = Number(required("CONTRACT_DEPLOYMENT_BLOCK"));
  let endBlock = await provider.getBlockNumber();
  while (endBlock >= deploymentBlock) {
    const fromBlock = Math.max(deploymentBlock, endBlock - blockBatchSize + 1);
    const events = await registry.queryFilter(
      registry.filters.ComplianceResultRegistered(recordKey), fromBlock, endBlock,
    );
    if (events.length) return events.at(-1);
    endBlock = fromBlock - 1;
  }
  return null;
}

async function writeComplianceReceipt(outputDirectory, payload) {
  const receiptPath = join(outputDirectory, "onchain-receipt.json");
  const temporaryPath = `${receiptPath}.${process.pid}.tmp`;
  await writeFile(temporaryPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  await rename(temporaryPath, receiptPath);
}

async function uploadComplianceBundle(recordKey, documentHash, outputDirectory) {
  const manifest = JSON.parse(
    await readFile(join(outputDirectory, "compliance-manifest.json"), "utf8"),
  );
  const bundle = await readFile(join(outputDirectory, "compliance-bundle.zip"));
  validateComplianceManifest(manifest, bundle, recordKey, documentHash);
  const transactions = [];
  let finalizationReceipt;

  if (await registry.hasComplianceResult(recordKey)) {
    const result = await registry.readComplianceResult(recordKey);
    validateFinalizedCompliance(result, manifest);
    const chunks = await readComplianceChunks(recordKey, Number(result.chunkCount));
    const stored = Buffer.concat(chunks);
    if (!stored.equals(bundle) || !equalHex(sha256(stored), result.bundleHash)) {
      throw new Error("Finalized on-chain compliance bytes do not match the local bundle");
    }
  } else {
    let offset = 0;
    let chunkIndex = 0;
    if (await registry.hasPendingComplianceUpload(recordKey)) {
      const pending = await registry.readComplianceUploadProgress(recordKey);
      const chunks = await readComplianceChunks(recordKey, Number(pending.chunkCount));
      const stored = validatePendingCompliance(pending, manifest, chunks);
      if (!bundle.subarray(0, stored.length).equals(stored)) {
        throw new Error("Pending compliance chunks do not match the local bundle prefix");
      }
      offset = stored.length;
      chunkIndex = chunks.length;
    } else {
      await sendComplianceTransaction(
        "begin",
        complianceRegistry.beginComplianceUpload(recordKey, {
          bundleHash: manifest.bundleHash,
          sourceDocumentHash: manifest.sourceDocumentHash,
          pipelineVersionHash: manifest.pipelineVersionHash,
          bundleSize: manifest.bundleSize,
        }),
        transactions,
      );
    }

    while (offset < bundle.length) {
      const chunk = await storableComplianceChunk(
        recordKey,
        chunkIndex,
        bundle.subarray(offset),
      );
      await sendComplianceTransaction(
        "chunk",
        complianceRegistry.appendComplianceChunk(recordKey, chunkIndex, chunk),
        transactions,
      );
      transactions.at(-1).chunkIndex = chunkIndex;
      transactions.at(-1).chunkBytes = chunk.length;
      offset += chunk.length;
      chunkIndex += 1;
    }

    finalizationReceipt = await sendComplianceTransaction(
      "finalize",
      complianceRegistry.finalizeComplianceUpload(recordKey),
      transactions,
    );

    const result = await registry.readComplianceResult(recordKey);
    validateFinalizedCompliance(result, manifest);
    const stored = Buffer.concat(
      await readComplianceChunks(recordKey, Number(result.chunkCount)),
    );
    if (!stored.equals(bundle) || !equalHex(sha256(stored), result.bundleHash)) {
      throw new Error("On-chain compliance verification failed after finalization");
    }
  }

  const result = await registry.readComplianceResult(recordKey);
  const finalizationTopic = registry.interface.getEvent("ComplianceResultRegistered").topicHash;
  let event = finalizationReceipt?.logs.find(
    (log) => equalHex(log.address, CONTRACT_ADDRESS)
      && equalHex(log.topics[0], finalizationTopic)
      && equalHex(log.topics[1], recordKey),
  );
  if (!event) {
    try {
      event = await complianceRegistrationEvent(recordKey);
    } catch (error) {
      // The event is only used for receipt metadata. The result and every stored
      // byte have already been verified above, so a provider's log limit must
      // not turn a finalized upload into a failed one.
      console.warn(`Could not look up compliance event for ${recordKey}: ${error.message}`);
    }
  }
  await writeComplianceReceipt(outputDirectory, {
    status: "finalized",
    verified: true,
    chainId: (await provider.getNetwork()).chainId.toString(),
    contractAddress: CONTRACT_ADDRESS,
    recordKey,
    bundleHash: result.bundleHash,
    bundleSize: Number(result.bundleSize),
    chunkCount: Number(result.chunkCount),
    chunkCommitment: result.chunkCommitment,
    sourceDocumentHash: result.sourceDocumentHash,
    pipelineVersionHash: result.pipelineVersionHash,
    submitter: result.submitter,
    registeredAt: Number(result.registeredAt),
    finalizationTxHash: event?.transactionHash ?? "",
    blockNumber: event?.blockNumber ?? null,
    transactions,
    files: manifest.files,
  });
}

async function restoreFinalizedCompliance(recordKey, outputDirectory) {
  const result = await registry.readComplianceResult(recordKey);
  const chunks = await readComplianceChunks(recordKey, Number(result.chunkCount));
  const bundle = Buffer.concat(chunks);
  if (
    bundle.length !== Number(result.bundleSize) ||
    !equalHex(sha256(bundle), result.bundleHash) ||
    !equalHex(complianceCommitment(chunks), result.chunkCommitment)
  ) {
    throw new Error("Existing on-chain compliance result failed reconstruction checks");
  }

  await mkdir(outputDirectory, { recursive: true });
  const bundlePath = join(outputDirectory, "compliance-bundle.zip");
  const temporaryPath = `${bundlePath}.${process.pid}.tmp`;
  await writeFile(temporaryPath, bundle);
  await rename(temporaryPath, bundlePath);
  await runComplianceTool(
    "Compliance bundle restore",
    join(projectRoot, "scripts", "restore-compliance-bundle.py"),
    ["--bundle", bundlePath, "--output-dir", outputDirectory],
    Buffer.alloc(0),
  );
}

async function readRawFile(recordKey) {
  const record = await registry.readRecordByKey(recordKey);
  const chunks = [];
  for (let index = 0; index < Number(record.documentChunkCount); index += 1) {
    const chunk = await registry.readDocumentChunk(recordKey, index);
    chunks.push(Buffer.from(getBytes(chunk)));
  }
  const rawFile = Buffer.concat(chunks);
  if (rawFile.length !== Number(record.documentSize)) {
    throw new InvalidOnChainPolicyError(`On-chain rawFile size mismatch for ${recordKey}`);
  }
  if (sha256(rawFile).toLowerCase() !== record.documentHash.toLowerCase()) {
    throw new InvalidOnChainPolicyError(`On-chain rawFile hash mismatch for ${recordKey}`);
  }
  if (!equalHex(complianceCommitment(chunks), record.documentChunkCommitment)) {
    throw new InvalidOnChainPolicyError(`On-chain rawFile chunk commitment mismatch for ${recordKey}`);
  }
  const metadataChunks = [];
  for (let index = 0; index < Number(record.metadataChunkCount); index += 1) {
    metadataChunks.push(Buffer.from(getBytes(await registry.readMetadataChunk(recordKey, index))));
  }
  const metadataBytes = Buffer.concat(metadataChunks);
  if (metadataBytes.length !== Number(record.metadataSize)
      || !equalHex(sha256(metadataBytes), record.metadataHash)
      || !equalHex(complianceCommitment(metadataChunks), record.metadataChunkCommitment)) {
    throw new InvalidOnChainPolicyError(`On-chain metadata integrity mismatch for ${recordKey}`);
  }
  let metadata;
  try {
    metadata = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(metadataBytes));
  } catch {
    throw new InvalidOnChainPolicyError(`On-chain metadata is not valid UTF-8 JSON for ${recordKey}`);
  }
  const metadataDocumentHash = typeof metadata?.documentHash === "string"
    ? (metadata.documentHash.startsWith("0x") ? metadata.documentHash : `0x${metadata.documentHash}`)
    : "";
  if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)
      || metadata.developer !== record.publisherEntity
      || metadata.publisherEntity !== record.publisherEntity
      || metadata.applicationName !== record.serviceName
      || metadata.serviceName !== record.serviceName
      || metadata.policyVersion !== record.policyVersion
      || metadata.effectiveDate !== record.effectiveDate
      || !equalHex(metadataDocumentHash, record.documentHash)) {
    throw new InvalidOnChainPolicyError(`On-chain metadata identity mismatch for ${recordKey}`);
  }
  return { rawFile, record };
}

async function callOffchainTool({ detectedAt, recordKey }) {
  const { rawFile, record } = await readRawFile(recordKey);
  const outputDirectory = join(complianceOutputRoot, recordKey.toLowerCase());
  await mkdir(outputDirectory, { recursive: true });

  console.log(
    `[${detectedAt}] processing compliance for ${record.serviceName} (${recordKey})`,
  );
  if (await registry.hasComplianceResult(recordKey)) {
    console.log(`[${detectedAt}] restoring existing on-chain compliance result`);
    await restoreFinalizedCompliance(recordKey, outputDirectory);
  } else {
    try {
      await runComplianceTool(
        "P1/P2/P3 compliance adapter",
        join(complianceRoot, "run_compliance.py"),
        [
          "--output-dir",
          outputDirectory,
          "--record-key",
          recordKey,
          "--document-hash",
          record.documentHash,
          "--high-risk",
          complianceHighRisk,
          "--model",
          complianceModel,
        ],
        rawFile,
      );
    } catch (error) {
      throw new ComplianceAnalysisError(error.message, { cause: error });
    }
  }
  console.log(`[${detectedAt}] uploading compliance bundle for ${recordKey}`);
  await uploadComplianceBundle(recordKey, record.documentHash, outputDirectory);
  console.log(`[${detectedAt}] compliance bundle finalized for ${recordKey}`);
}

function positiveInteger(name, fallback) {
  const value = process.env[name];
  if (value === undefined) return fallback;
  const parsed = Number.parseInt(value, 10);
  if (!Number.isSafeInteger(parsed) || parsed < 1) {
    throw new Error(`${name} must be a positive integer`);
  }
  return parsed;
}

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function saveState(statePath, state) {
  await mkdir(dirname(statePath), { recursive: true, mode: 0o700 });
  const temporaryPath = `${statePath}.${process.pid}.tmp`;
  await writeFile(temporaryPath, `${JSON.stringify(state, null, 2)}\n`, { encoding: "utf8", mode: 0o600 });
  await rename(temporaryPath, statePath);
}

async function processBlockRange(fromBlock, toBlock, state, statePath, eventTopic) {
  let logs;
  try {
    logs = await provider.getLogs({
      address: CONTRACT_ADDRESS,
      topics: [eventTopic],
      fromBlock,
      toBlock,
    });
  } catch (error) {
    if (fromBlock === toBlock) throw error;
    const middle = Math.floor((fromBlock + toBlock) / 2);
    await processBlockRange(fromBlock, middle, state, statePath, eventTopic);
    await processBlockRange(middle + 1, toBlock, state, statePath, eventTopic);
    return;
  }

  for (const log of logs) {
    const eventId = `${log.transactionHash}:${log.index}`;
    if (state.processedEvents[eventId] !== undefined) continue;

    const parsed = registry.interface.parseLog(log);
    try {
      await callOffchainTool({
        detectedAt: new Date().toISOString(),
        recordKey: parsed.args.recordKey,
      });
    } catch (error) {
      if (!(error instanceof InvalidOnChainPolicyError)) throw error;
      console.error(`Skipping invalid policy ${parsed.args.recordKey}: ${error.message}`);
      state.invalidEvents[eventId] = {
        recordKey: parsed.args.recordKey,
        blockNumber: log.blockNumber,
        reason: error.message,
      };
    }

    state.processedEvents[eventId] = log.blockNumber;
    await saveState(statePath, state);
  }

  state.lastProcessedBlock = toBlock;
  const oldestRememberedBlock = Math.max(0, toBlock - 10_000);
  state.processedEvents = Object.fromEntries(
    Object.entries(state.processedEvents).filter(
      ([, blockNumber]) => blockNumber >= oldestRememberedBlock,
    ),
  );
  await saveState(statePath, state);
}

async function listen() {
  const network = await provider.getNetwork();
  if (network.chainId !== BASE_CHAIN_ID) {
    throw new Error(`RPC returned chain ID ${network.chainId}; expected Base Mainnet ${BASE_CHAIN_ID}`);
  }
  const code = await provider.getCode(CONTRACT_ADDRESS);
  if (code === "0x") {
    throw new Error(`No contract bytecode found at ${CONTRACT_ADDRESS} on Base Mainnet`);
  }
  const expectedCodeHash = required("CONTRACT_RUNTIME_CODE_HASH");
  if (keccak256(code).toLowerCase() !== expectedCodeHash.toLowerCase()) {
    throw new Error(`CONTRACT_RUNTIME_CODE_HASH does not match the code at ${CONTRACT_ADDRESS}`);
  }
  if (!(await registry.complianceUploaders(complianceUploaderAddress))) {
    throw new Error(
      `Compliance uploader ${complianceUploaderAddress} is not authorized by the contract`,
    );
  }
  const chainId = network.chainId.toString();
  const confirmations = positiveInteger("EVENT_CONFIRMATIONS", 3);
  const latestBlock = await provider.getBlockNumber();
  required("CONTRACT_DEPLOYMENT_BLOCK");
  const deploymentBlock = positiveInteger("CONTRACT_DEPLOYMENT_BLOCK", 0);
  if (deploymentBlock > latestBlock) {
    throw new Error(`CONTRACT_DEPLOYMENT_BLOCK ${deploymentBlock} is above the Base head ${latestBlock}`);
  }
  const initialBlock = deploymentBlock - 1;
  const deploymentAnchor = (await provider.getBlock(deploymentBlock))?.hash;
  if (!deploymentAnchor) {
    throw new Error(`Contract deployment block ${deploymentBlock} was not found`);
  }
  const chainIdentity = [
    chainId,
    CONTRACT_ADDRESS.toLowerCase(),
    deploymentBlock,
    deploymentAnchor,
  ].join(":");
  const statePath =
    process.env.LISTENER_STATE_PATH ??
    join(tmpdir(), `privacy-policy-listener-${chainId}-${CONTRACT_ADDRESS.toLowerCase()}.json`);
  const state = await loadState(statePath, initialBlock, latestBlock, chainIdentity);
  const eventTopic = registry.interface.getEvent("TrustedPolicyRecordRegistered").topicHash;

  console.log(`Listening for policy registrations on ${CONTRACT_ADDRESS}...`);
  console.log(`Authorized compliance uploader: ${complianceUploaderAddress}`);
  console.log(
    `chainId=${chainId} confirmations=${confirmations} lastProcessedBlock=${state.lastProcessedBlock}`,
  );

  let analysisPaused = false;
  while (running) {
    if (analysisPaused) {
      await delay(pollIntervalMs);
      continue;
    }
    try {
      const headBlock = await provider.getBlockNumber();
      const safeBlock = headBlock - confirmations;

      while (running && state.lastProcessedBlock < safeBlock) {
        const fromBlock = state.lastProcessedBlock + 1;
        const toBlock = Math.min(fromBlock + blockBatchSize - 1, safeBlock);
        await processBlockRange(fromBlock, toBlock, state, statePath, eventTopic);
      }
    } catch (error) {
      if (error instanceof ComplianceAnalysisError) {
        // Keep the cursor before this event so restarting retries it exactly once.
        // Repeated automatic attempts can incur paid model calls every poll.
        analysisPaused = true;
        console.error(`Compliance analysis failed; listener paused until restart: ${error.message}`);
      } else {
        console.error(`Event polling failed; retrying: ${error.message}`);
      }
    }

    if (running) await delay(pollIntervalMs);
  }
}

void listen().catch((error) => {
  console.error(`Listener stopped: ${error.message}`);
  provider.destroy();
  process.exit(1);
});

async function shutdown(signal) {
  console.log(`\nReceived ${signal}; stopping listener.`);
  running = false;
  provider.destroy();
  process.exit(0);
}

process.on("SIGINT", () => void shutdown("SIGINT"));
process.on("SIGTERM", () => void shutdown("SIGTERM"));
