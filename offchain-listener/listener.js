import { readFile, rename, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Contract, JsonRpcProvider } from "ethers";

const { RPC_URL, CONTRACT_ADDRESS } = process.env;

if (!RPC_URL || !CONTRACT_ADDRESS) {
  console.error(
    "Missing configuration. Set RPC_URL and CONTRACT_ADDRESS before starting the listener.",
  );
  process.exit(1);
}

const registryAbi = [
  "event TrustedPolicyRecordRegistered(bytes32 indexed recordKey, bytes32 indexed documentHash, bytes32 indexed metadataHash, bytes32 previousRecordKey, address registrant, uint64 registeredAt)",
];

const provider = new JsonRpcProvider(RPC_URL);
const registry = new Contract(CONTRACT_ADDRESS, registryAbi, provider);
const pollIntervalMs = positiveInteger("POLL_INTERVAL_MS", 5_000);
const blockBatchSize = positiveInteger("BLOCK_BATCH_SIZE", 2_000);
let running = true;

async function callOffchainTool({ detectedAt, policyId }) {
  // Replace this terminal output with the real tool call when that tool exists.
  console.log(`[${detectedAt}] policyId=${policyId}`);
}

function positiveInteger(name, fallback) {
  const value = process.env[name];
  if (value === undefined) return fallback;
  const parsed = Number.parseInt(value, 10);
  if (!Number.isSafeInteger(parsed) || parsed < 0) {
    throw new Error(`${name} must be a non-negative integer`);
  }
  return parsed;
}

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function loadState(statePath, initialBlock, chainIdentity) {
  try {
    const state = JSON.parse(await readFile(statePath, "utf8"));
    if (state.chainIdentity !== chainIdentity) {
      console.log("Listener state belongs to a different chain instance; resetting cursor.");
      return { chainIdentity, lastProcessedBlock: initialBlock, processedEvents: {} };
    }
    return {
      chainIdentity,
      lastProcessedBlock: Number(state.lastProcessedBlock),
      processedEvents: state.processedEvents ?? {},
    };
  } catch (error) {
    if (error.code !== "ENOENT") {
      console.warn(`Could not read listener state; starting fresh: ${error.message}`);
    }
    return { chainIdentity, lastProcessedBlock: initialBlock, processedEvents: {} };
  }
}

async function saveState(statePath, state) {
  const temporaryPath = `${statePath}.${process.pid}.tmp`;
  await writeFile(temporaryPath, `${JSON.stringify(state, null, 2)}\n`, "utf8");
  await rename(temporaryPath, statePath);
}

async function processBlockRange(fromBlock, toBlock, state, statePath, eventTopic) {
  const logs = await provider.getLogs({
    address: CONTRACT_ADDRESS,
    topics: [eventTopic],
    fromBlock,
    toBlock,
  });

  for (const log of logs) {
    const eventId = `${log.transactionHash}:${log.index}`;
    if (state.processedEvents[eventId] !== undefined) continue;

    const parsed = registry.interface.parseLog(log);
    await callOffchainTool({
      detectedAt: new Date().toISOString(),
      policyId: parsed.args.recordKey,
    });

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
  const chainId = network.chainId.toString();
  const defaultConfirmations = chainId === "31337" ? 0 : 3;
  const confirmations = positiveInteger("EVENT_CONFIRMATIONS", defaultConfirmations);
  const latestBlock = await provider.getBlockNumber();
  const genesisBlock = await provider.getBlock(0);
  const chainIdentity = `${chainId}:${genesisBlock.hash}`;
  const configuredStartBlock = process.env.CONTRACT_DEPLOYMENT_BLOCK;
  const initialBlock = configuredStartBlock
    ? positiveInteger("CONTRACT_DEPLOYMENT_BLOCK", latestBlock) - 1
    : latestBlock;
  const statePath =
    process.env.LISTENER_STATE_PATH ??
    join(tmpdir(), `privacy-policy-listener-${chainId}-${CONTRACT_ADDRESS.toLowerCase()}.json`);
  const state = await loadState(statePath, initialBlock, chainIdentity);
  const eventTopic = registry.interface.getEvent("TrustedPolicyRecordRegistered").topicHash;

  console.log(`Listening for policy registrations on ${CONTRACT_ADDRESS}...`);
  console.log(
    `chainId=${chainId} confirmations=${confirmations} lastProcessedBlock=${state.lastProcessedBlock}`,
  );

  while (running) {
    try {
      const headBlock = await provider.getBlockNumber();
      const safeBlock = headBlock - confirmations;

      while (running && state.lastProcessedBlock < safeBlock) {
        const fromBlock = state.lastProcessedBlock + 1;
        const toBlock = Math.min(fromBlock + blockBatchSize - 1, safeBlock);
        await processBlockRange(fromBlock, toBlock, state, statePath, eventTopic);
      }
    } catch (error) {
      console.error(`Event polling failed; retrying: ${error.message}`);
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
