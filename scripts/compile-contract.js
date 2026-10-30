import { spawn } from "node:child_process";
import { access, mkdir, readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { homedir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const sourceName = "contracts/TrustedPolicyRegistry.sol";
const compilerFile = "soljson-v0.8.24+commit.e11b9ed9.js";
const compilerDirectories = [
  process.env.HARDHAT_COMPILERS_CACHE_DIR,
  join(homedir(), "Library", "Caches", "hardhat-nodejs", "compilers-v3", "wasm"),
  join(process.env.XDG_CACHE_HOME || join(homedir(), ".cache"), "hardhat-nodejs", "compilers-v3", "wasm"),
].filter(Boolean);

async function cachedCompiler() {
  for (const directory of compilerDirectories) {
    const path = join(directory, compilerFile);
    try {
      await access(path);
      return path;
    } catch {
      // A fresh machine can let Hardhat download the exact configured compiler.
    }
  }
  return null;
}

async function compileWithCache(path) {
  const require = createRequire(import.meta.url);
  const soljson = require(path);
  const compile = soljson.cwrap("solidity_compile", "string", ["string", "number"]);
  const input = {
    language: "Solidity",
    sources: {
      [sourceName]: { content: await readFile(join(root, sourceName), "utf8") },
    },
    settings: {
      optimizer: { enabled: true, runs: 200 },
      outputSelection: {
        "*": { "*": ["abi", "evm.bytecode", "evm.deployedBytecode"] },
      },
    },
  };
  const output = JSON.parse(compile(JSON.stringify(input), 0));
  const errors = (output.errors || []).filter((item) => item.severity === "error");
  if (errors.length) {
    throw new Error(errors.map((item) => item.formattedMessage).join("\n"));
  }
  const contract = output.contracts?.[sourceName]?.TrustedPolicyRegistry;
  if (!contract?.evm?.bytecode?.object || !contract?.abi) {
    throw new Error("Solidity compiler did not produce the expected registry artifact");
  }
  const artifact = {
    _format: "hh3-artifact-1",
    contractName: "TrustedPolicyRegistry",
    sourceName,
    abi: contract.abi,
    bytecode: `0x${contract.evm.bytecode.object}`,
    deployedBytecode: `0x${contract.evm.deployedBytecode.object}`,
    linkReferences: contract.evm.bytecode.linkReferences || {},
    deployedLinkReferences: contract.evm.deployedBytecode.linkReferences || {},
    immutableReferences: contract.evm.deployedBytecode.immutableReferences || {},
    inputSourceName: sourceName,
  };
  const artifactPath = join(root, "artifacts", sourceName, "TrustedPolicyRegistry.json");
  await mkdir(join(root, "artifacts", sourceName), { recursive: true });
  await writeFile(artifactPath, `${JSON.stringify(artifact, null, 2)}\n`);
  console.log(`Compiled TrustedPolicyRegistry with cached Solidity 0.8.24 (${contract.evm.deployedBytecode.object.length / 2} runtime bytes).`);
}

async function compileWithHardhat() {
  const binary = join(root, "node_modules", ".bin", process.platform === "win32" ? "hardhat.cmd" : "hardhat");
  await new Promise((resolve, reject) => {
    const child = spawn(binary, ["compile"], { cwd: root, stdio: "inherit" });
    child.once("error", reject);
    child.once("exit", (code) => code === 0 ? resolve() : reject(new Error(`Hardhat compile failed with exit code ${code}`)));
  });
}

const compiler = await cachedCompiler();
if (compiler) await compileWithCache(compiler);
else await compileWithHardhat();
