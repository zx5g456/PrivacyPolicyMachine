import { readFile } from "node:fs/promises";
import { parseEnv } from "node:util";
import { fileURLToPath } from "node:url";
import { ZeroAddress, getAddress } from "ethers";

export const configPath = fileURLToPath(new URL("./base-mainnet.env", import.meta.url));
export const BASE_CHAIN_ID = 8453n;

export async function loadBaseEnv({ omit = [] } = {}) {
  let source;
  try {
    source = await readFile(configPath, "utf8");
  } catch (error) {
    if (error.code === "ENOENT") {
      throw new Error(`Missing ${configPath}. Copy config/base-mainnet.env.example and fill it in.`);
    }
    throw error;
  }
  for (const [key, value] of Object.entries(parseEnv(source))) {
    if (omit.includes(key)) delete process.env[key];
    else process.env[key] = value;
  }
}

export function required(name) {
  const value = (process.env[name] ?? "").trim();
  if (!value) throw new Error(`Set ${name} in config/base-mainnet.env`);
  return value;
}

export function publisherWallets() {
  let parsed;
  try {
    parsed = JSON.parse(required("PUBLISHER_WALLETS_JSON"));
  } catch (error) {
    throw new Error(`PUBLISHER_WALLETS_JSON must be a JSON object: ${error.message}`);
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed) || !Object.keys(parsed).length) {
    throw new Error("PUBLISHER_WALLETS_JSON must map at least one developer name to a wallet address");
  }
  return Object.fromEntries(Object.entries(parsed).map(([developer, address]) => {
    if (!developer.trim() || developer !== developer.trim() || typeof address !== "string") {
      throw new Error("Every publisher needs a nonempty developer name and wallet address");
    }
    try {
      const normalized = getAddress(address);
      if (normalized === ZeroAddress) throw new Error("zero address");
      return [developer, normalized];
    } catch {
      throw new Error(`Invalid wallet address for publisher ${developer}`);
    }
  }));
}

export function assertBaseChainId() {
  const configured = required("EXPECTED_CHAIN_ID");
  if (configured !== String(BASE_CHAIN_ID)) {
    throw new Error(`EXPECTED_CHAIN_ID must be ${BASE_CHAIN_ID} for Base Mainnet`);
  }
}
