import { access } from "node:fs/promises";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { Contract, FetchRequest, JsonRpcProvider, Wallet, getAddress, keccak256 } from "ethers";
import {
  BASE_CHAIN_ID, assertBaseChainId, loadBaseEnv, publisherWallets, required,
} from "../config/load-base-env.js";

const children = new Set();
let stopping = false;

function command(name) {
  return process.platform === "win32" ? `${name}.cmd` : name;
}

function start(label, executable, args, options = {}) {
  const child = spawn(executable, args, {
    cwd: options.cwd ?? process.cwd(),
    env: options.env ?? process.env,
    stdio: options.stdio ?? "inherit",
    detached: process.platform !== "win32",
  });
  children.add(child);
  child.once("exit", (code, signal) => {
    children.delete(child);
    if (!stopping && options.required !== false) {
      console.error(`${label} stopped unexpectedly (${signal ?? `exit ${code}`}).`);
      void shutdown(1);
    }
  });
  return child;
}

function run(label, executable, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(executable, args, {
      cwd: options.cwd ?? process.cwd(),
      env: options.env ?? process.env,
      stdio: options.capture ? ["ignore", "pipe", "inherit"] : "inherit",
    });
    let output = "";
    if (options.capture) {
      child.stdout.on("data", (chunk) => {
        const text = chunk.toString();
        output += text;
        process.stdout.write(text);
      });
    }
    child.once("error", reject);
    child.once("exit", (code) => {
      if (code === 0) resolve(output);
      else reject(new Error(`${label} failed with exit code ${code}`));
    });
  });
}

async function verifyBaseDeployment(publishers, complianceAddress) {
  assertBaseChainId();
  const request = new FetchRequest(required("RPC_URL"));
  request.timeout = 30_000;
  const provider = new JsonRpcProvider(request, undefined, { batchMaxCount: 1 });
  try {
    const network = await provider.getNetwork();
    if (network.chainId !== BASE_CHAIN_ID) {
      throw new Error(`RPC returned chain ID ${network.chainId}; expected Base Mainnet ${BASE_CHAIN_ID}`);
    }
    const contractAddress = getAddress(required("CONTRACT_ADDRESS"));
    const block = Number(required("CONTRACT_DEPLOYMENT_BLOCK"));
    if (!Number.isSafeInteger(block) || block < 1 || block > await provider.getBlockNumber()) {
      throw new Error("CONTRACT_DEPLOYMENT_BLOCK must be a mined Base Mainnet block");
    }
    const code = await provider.getCode(contractAddress);
    if (code === "0x") {
      throw new Error(`No contract bytecode found at ${contractAddress} on Base Mainnet`);
    }
    const expectedCodeHash = required("CONTRACT_RUNTIME_CODE_HASH");
    if (keccak256(code).toLowerCase() !== expectedCodeHash.toLowerCase()) {
      throw new Error(`CONTRACT_RUNTIME_CODE_HASH does not match the code at ${contractAddress}`);
    }
    const registry = new Contract(contractAddress, [
      "function owner() view returns (address)",
      "function getPublisherOwner(string) view returns (address)",
      "function complianceUploaders(address) view returns (bool)",
    ], provider);
    await registry.owner();
    if (!(await registry.complianceUploaders(complianceAddress))) {
      throw new Error(`Compliance wallet ${complianceAddress} is not authorized on the contract`);
    }
    for (const [name, address] of Object.entries(publishers)) {
      if ((await registry.getPublisherOwner(name)).toLowerCase() !== address.toLowerCase()) {
        throw new Error(`Publisher ${name} is not authorized as ${address} on the contract`);
      }
    }
    return { contractAddress, block };
  } finally {
    provider.destroy();
  }
}

async function shutdown(exitCode = 0) {
  if (stopping) return;
  stopping = true;
  console.log("\nStopping local Privacy Policy Machine services...");
  for (const child of children) {
    if (process.platform === "win32") child.kill("SIGTERM");
    else process.kill(-child.pid, "SIGTERM");
  }
  await Promise.allSettled(
    [...children].map(
      (child) => new Promise((resolve) => child.once("exit", resolve)),
    ),
  );
  process.exit(exitCode);
}

async function main() {
  await loadBaseEnv();
  const python = process.platform === "win32" ? ".venv\\Scripts\\python.exe" : ".venv/bin/python";
  const publishers = publisherWallets();
  let complianceAddress;
  try {
    complianceAddress = new Wallet(required("COMPLIANCE_PRIVATE_KEY")).address;
  } catch {
    throw new Error("COMPLIANCE_PRIVATE_KEY must be a valid private key in config/base-mainnet.env");
  }
  required("OPENAI_API_KEY");
  await access(python).catch(() => {
    throw new Error(`Python virtual environment not found at ${python}. Create it and install requirements first.`);
  });

  const compileEnv = { ...process.env };
  delete compileEnv.BASE_DEPLOYER_PRIVATE_KEY;
  delete compileEnv.COMPLIANCE_PRIVATE_KEY;
  delete compileEnv.OPENAI_API_KEY;
  console.log("Compiling Solidity contract...");
  await run("contract compilation", command("npm"), ["run", "contract:compile"], { env: compileEnv });

  console.log("Checking Base Mainnet contract and wallet authorizations...");
  const { contractAddress, block } = await verifyBaseDeployment(publishers, complianceAddress);

  const sharedEnv = {
    ...process.env,
    CONTRACT_ADDRESS: contractAddress,
    CONTRACT_DEPLOYMENT_BLOCK: String(block),
    LISTENER_STATE_PATH: process.env.LISTENER_STATE_PATH ??
      fileURLToPath(new URL("../data/base-mainnet/listener-state.json", import.meta.url)),
  };
  delete sharedEnv.BASE_DEPLOYER_PRIVATE_KEY;
  const serverEnv = { ...sharedEnv };
  delete serverEnv.COMPLIANCE_PRIVATE_KEY;
  delete serverEnv.OPENAI_API_KEY;

  console.log("Starting local listener and web server on Base Mainnet...");
  start("event listener", command("npm"), ["start"], {
    cwd: new URL("../offchain-listener", import.meta.url),
    env: sharedEnv,
  });
  start("web server", python, ["-m", "server.app"], { env: serverEnv });

  console.log("\nLocal services are ready for Base Mainnet:");
  console.log(`  CONTRACT_ADDRESS=${contractAddress}`);
  console.log(`  CONTRACT_DEPLOYMENT_BLOCK=${block}`);
  console.log("  Open the web URL printed by the Python server.");
  console.log("  Press Ctrl+C to stop everything.\n");
}

process.on("SIGINT", () => void shutdown(0));
process.on("SIGTERM", () => void shutdown(0));

main().catch((error) => {
  console.error(error.message);
  void shutdown(1);
});
