import { readFile } from "node:fs/promises";

function matchesChainIdentity(stored, current) {
  if (stored === current) return true;
  if (typeof stored !== "string") return false;

  // Earlier listener state included the genesis hash between chain ID and address.
  // The deployment block hash already anchors this contract to one chain instance.
  const parts = stored.split(":");
  return parts.length === 5 &&
    /^0x[0-9a-fA-F]{64}$/.test(parts[1]) &&
    [parts[0], parts[2], parts[3], parts[4]].join(":") === current;
}

export async function loadState(statePath, initialBlock, latestBlock, chainIdentity) {
  const freshState = () => ({
    chainIdentity,
    lastProcessedBlock: initialBlock,
    processedEvents: {},
    invalidEvents: {},
  });

  try {
    const state = JSON.parse(await readFile(statePath, "utf8"));
    if (!matchesChainIdentity(state.chainIdentity, chainIdentity)) {
      console.log("Listener state belongs to a different chain instance; resetting cursor.");
      return freshState();
    }
    const lastProcessedBlock = Number(state.lastProcessedBlock);
    if (
      !Number.isSafeInteger(lastProcessedBlock) ||
      lastProcessedBlock < initialBlock ||
      lastProcessedBlock > latestBlock
    ) {
      console.log("Listener cursor is outside this deployment's block range; resetting cursor.");
      return freshState();
    }
    return {
      chainIdentity,
      lastProcessedBlock,
      processedEvents: state.processedEvents ?? {},
      invalidEvents: state.invalidEvents ?? {},
    };
  } catch (error) {
    if (error.code !== "ENOENT") {
      console.warn(`Could not read listener state; starting fresh: ${error.message}`);
    }
    return freshState();
  }
}
