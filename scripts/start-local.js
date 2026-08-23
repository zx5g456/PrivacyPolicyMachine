import { access } from "node:fs/promises";
import { spawn } from "node:child_process";

const rpcUrl = process.env.RPC_URL ?? "http://127.0.0.1:8545";
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

async function waitForRpc(timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(rpcUrl, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "eth_chainId", params: [] }),
      });
      if (response.ok) return;
    } catch {
      // The node is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Local Ethereum RPC did not start at ${rpcUrl}`);
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
  const python = process.platform === "win32" ? ".venv\\Scripts\\python.exe" : ".venv/bin/python";
  await access(python).catch(() => {
    throw new Error(`Python virtual environment not found at ${python}. Create it and install requirements first.`);
  });

  console.log("Compiling Solidity contract...");
  await run("contract compilation", command("npm"), ["run", "contract:compile"]);

  console.log("Starting local Hardhat chain...");
  start("Hardhat chain", command("npm"), ["run", "chain"]);
  await waitForRpc();

  console.log("Deploying TrustedPolicyRegistry...");
  const deployOutput = await run(
    "contract deployment",
    command("npm"),
    ["run", "contract:deploy"],
    { capture: true, env: { ...process.env, RPC_URL: rpcUrl } },
  );
  const address = deployOutput.match(/TrustedPolicyRegistry deployed to:\s*(0x[a-fA-F0-9]{40})/)?.[1];
  if (!address) throw new Error("Could not read CONTRACT_ADDRESS from deployment output");
  const deploymentBlock = deployOutput.match(/CONTRACT_DEPLOYMENT_BLOCK=(\d+)/)?.[1];
  if (!deploymentBlock) throw new Error("Could not read CONTRACT_DEPLOYMENT_BLOCK from deployment output");

  const sharedEnv = {
    ...process.env,
    RPC_URL: rpcUrl,
    CONTRACT_ADDRESS: address,
    CONTRACT_DEPLOYMENT_BLOCK: deploymentBlock,
  };

  console.log("Starting off-chain listener and web server...");
  start("event listener", command("npm"), ["start"], {
    cwd: new URL("../offchain-listener", import.meta.url),
    env: sharedEnv,
  });
  start("web server", python, ["-m", "server.app"], { env: sharedEnv });

  console.log("\nLocal environment is ready:");
  console.log(`  RPC_URL=${rpcUrl}`);
  console.log(`  CONTRACT_ADDRESS=${address}`);
  console.log(`  CONTRACT_DEPLOYMENT_BLOCK=${deploymentBlock}`);
  console.log("  Open the web URL printed by the Python server.");
  console.log("  Press Ctrl+C to stop everything.\n");
}

process.on("SIGINT", () => void shutdown(0));
process.on("SIGTERM", () => void shutdown(0));

main().catch((error) => {
  console.error(error.message);
  void shutdown(1);
});
