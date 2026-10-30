import { mkdir, open, readFile, rename, unlink, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  Contract, ContractFactory, FetchRequest, JsonRpcProvider, Transaction,
  Wallet, ZeroAddress, formatEther, getAddress, getCreateAddress, keccak256,
} from "ethers";
import {
  BASE_CHAIN_ID, assertBaseChainId, configPath, loadBaseEnv,
  publisherWallets, required,
} from "../config/load-base-env.js";

const root = fileURLToPath(new URL("../", import.meta.url));
const directory = join(root, "data", "base-mainnet");
const deploymentPath = join(directory, "deployment.json");
const journalPath = join(directory, "pending-transactions.json");
const explorer = "https://basescan.org";

function walletFromConfig(name) {
  try {
    return new Wallet(required(name));
  } catch {
    throw new Error(`${name} must be a valid 0x-prefixed private key in config/base-mainnet.env`);
  }
}

function addressFromConfig(name) {
  const value = (process.env[name] ?? "").trim();
  if (!value) return null;
  try {
    const address = getAddress(value);
    if (address === ZeroAddress) throw new Error("zero address");
    return address;
  } catch {
    throw new Error(`${name} must be a valid Ethereum address`);
  }
}

async function readJson(path) {
  try {
    return JSON.parse(await readFile(path, "utf8"));
  } catch (error) {
    if (error.code === "ENOENT") return null;
    throw error;
  }
}

async function saveJson(path, value) {
  await mkdir(directory, { recursive: true, mode: 0o700 });
  const temporary = `${path}.${process.pid}.tmp`;
  await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 });
  await rename(temporary, path);
}

function sameAddresses(first, second) {
  const names = Object.keys(first).sort();
  return names.length === Object.keys(second).length &&
    names.every((name) => second[name]?.toLowerCase() === first[name].toLowerCase());
}

async function connect() {
  assertBaseChainId();
  const rpcUrl = required("RPC_URL");
  const request = new FetchRequest(rpcUrl);
  request.timeout = 30_000;
  const provider = new JsonRpcProvider(request, undefined, { batchMaxCount: 1 });
  const network = await provider.getNetwork();
  if (network.chainId !== BASE_CHAIN_ID) {
    provider.destroy();
    throw new Error(`RPC returned chain ID ${network.chainId}; Base Mainnet requires ${BASE_CHAIN_ID}. No transaction sent.`);
  }
  return provider;
}

async function sendRecordedTransaction(provider, signer, journal, phase, transactionRequest) {
  let entry = journal.transactions[phase];
  if (!entry) {
    const nonce = await provider.getTransactionCount(signer.address, "pending");
    const estimate = await signer.estimateGas(transactionRequest);
    const gasLimit = estimate * 12n / 10n;
    const fees = await provider.getFeeData();
    const gasPriceCeiling = fees.maxFeePerGas ?? fees.gasPrice;
    if (gasPriceCeiling == null) throw new Error("RPC did not return a gas price");
    const executionFeeCeiling = gasLimit * gasPriceCeiling;
    const balance = await provider.getBalance(signer.address);
    console.log(`${phase}: estimated execution gas ${estimate}; L2 execution fee ceiling ${formatEther(executionFeeCeiling)} ETH, plus Base L1 data fee.`);
    if (balance < executionFeeCeiling) {
      throw new Error(`${signer.address} has only ${formatEther(balance)} Base ETH. Fund it before retrying ${phase}.`);
    }
    const populated = await signer.populateTransaction({ ...transactionRequest, gasLimit, nonce });
    const rawTransaction = await signer.signTransaction(populated);
    entry = { txHash: Transaction.from(rawTransaction).hash, rawTransaction };
    journal.transactions[phase] = entry;
    // Persist signed bytes before broadcasting, so a restart cannot create a duplicate transaction.
    await saveJson(journalPath, journal);
  }
  const signed = Transaction.from(entry.rawTransaction);
  if (signed.hash !== entry.txHash || signed.chainId !== BASE_CHAIN_ID ||
      signed.from?.toLowerCase() !== signer.address.toLowerCase()) {
    throw new Error(`Saved ${phase} transaction does not match the configured Base signer`);
  }
  let receipt = await provider.getTransactionReceipt(entry.txHash);
  if (!receipt && !(await provider.getTransaction(entry.txHash))) {
    try {
      await provider.broadcastTransaction(entry.rawTransaction);
    } catch (error) {
      if (!(await provider.getTransaction(entry.txHash)) &&
          !(await provider.getTransactionReceipt(entry.txHash))) throw error;
    }
  }
  console.log(`${phase}: ${explorer}/tx/${entry.txHash}`);
  receipt ??= await provider.waitForTransaction(entry.txHash, 1, 180_000);
  if (!receipt) throw new Error(`${phase} confirmation timed out. Rerun the same command to resume.`);
  if (receipt.status !== 1) throw new Error(`${phase} reverted. Inspect the saved transaction before retrying.`);
  return receipt;
}

async function verifyDeployment(provider, record, artifact, deployer, compliance, publishers, desiredOwner) {
  if (record.chainId !== Number(BASE_CHAIN_ID) || record.bytecodeHash !== keccak256(artifact.bytecode) ||
      record.deployer !== deployer.address || record.complianceUploader !== compliance.address ||
      record.desiredOwner !== desiredOwner || !sameAddresses(record.publisherOwners, publishers)) {
    throw new Error("Saved Base deployment differs from this contract or configuration. Inspect data/base-mainnet before retrying.");
  }
  const receipt = await provider.getTransactionReceipt(record.deploymentTxHash);
  const code = await provider.getCode(record.contractAddress);
  if (!receipt || receipt.status !== 1 || receipt.blockHash !== record.deploymentBlockHash ||
      receipt.contractAddress?.toLowerCase() !== record.contractAddress.toLowerCase() ||
      code === "0x" || keccak256(code) !== record.runtimeCodeHash) {
    throw new Error("Saved Base deployment transaction or bytecode could not be verified");
  }
  const contract = new Contract(record.contractAddress, artifact.abi, provider);
  const owner = await contract.owner();
  const pendingOwner = await contract.pendingOwner();
  if (owner !== deployer.address && owner !== desiredOwner) {
    throw new Error(`Unexpected registry owner ${owner}`);
  }
  if (desiredOwner !== deployer.address && owner !== desiredOwner && pendingOwner !== desiredOwner) {
    throw new Error(`Expected pending owner ${desiredOwner}, found ${pendingOwner}`);
  }
  if (!(await contract.complianceUploaders(compliance.address))) {
    throw new Error("Compliance wallet is not authorized on the saved deployment");
  }
  for (const [name, address] of Object.entries(publishers)) {
    if ((await contract.getPublisherOwner(name)).toLowerCase() !== address.toLowerCase()) {
      throw new Error(`Publisher ${name} is not authorized on the saved deployment`);
    }
  }
  return contract;
}

async function writeDeploymentToEnv(address, blockNumber, runtimeCodeHash) {
  let source = await readFile(configPath, "utf8");
  for (const [name, value] of [
    ["CONTRACT_ADDRESS", address],
    ["CONTRACT_DEPLOYMENT_BLOCK", String(blockNumber)],
    ["CONTRACT_RUNTIME_CODE_HASH", runtimeCodeHash],
  ]) {
    const configured = (process.env[name] ?? "").trim();
    if (configured && configured.toLowerCase() !== value.toLowerCase()) {
      throw new Error(`${name} in config/base-mainnet.env conflicts with the verified deployment`);
    }
    const line = new RegExp(`^${name}=.*$`, "m");
    source = line.test(source) ? source.replace(line, `${name}=${value}`) : `${source.trimEnd()}\n${name}=${value}\n`;
    process.env[name] = value;
  }
  const temporary = `${configPath}.${process.pid}.tmp`;
  await writeFile(temporary, source, { mode: 0o600 });
  await rename(temporary, configPath);
}

async function status(provider, publishers) {
  console.log(`Network: Base Mainnet (${BASE_CHAIN_ID})`);
  const deployerKey = (process.env.BASE_DEPLOYER_PRIVATE_KEY ?? "").trim();
  const complianceKey = (process.env.COMPLIANCE_PRIVATE_KEY ?? "").trim();
  const deployer = deployerKey ? walletFromConfig("BASE_DEPLOYER_PRIVATE_KEY") : null;
  const compliance = complianceKey ? walletFromConfig("COMPLIANCE_PRIVATE_KEY") : null;
  if (deployer) console.log(`Deployer: ${deployer.address}; balance ${formatEther(await provider.getBalance(deployer.address))} ETH`);
  if (compliance) console.log(`Compliance uploader: ${compliance.address}; balance ${formatEther(await provider.getBalance(compliance.address))} ETH`);
  for (const [name, address] of Object.entries(publishers)) {
    console.log(`Publisher ${name}: ${address}; balance ${formatEther(await provider.getBalance(address))} ETH`);
  }
  const contractAddress = addressFromConfig("CONTRACT_ADDRESS");
  if (!contractAddress) {
    console.log("CONTRACT_ADDRESS is blank; no deployment is configured.");
    return;
  }
  const code = await provider.getCode(contractAddress);
  if (code === "0x") throw new Error(`No contract bytecode at ${contractAddress}`);
  const runtimeCodeHash = keccak256(code);
  const expectedCodeHash = (process.env.CONTRACT_RUNTIME_CODE_HASH ?? "").trim();
  if (expectedCodeHash && expectedCodeHash.toLowerCase() !== runtimeCodeHash.toLowerCase()) {
    throw new Error(`CONTRACT_RUNTIME_CODE_HASH does not match the code at ${contractAddress}`);
  }
  const abi = [
    "function owner() view returns (address)",
    "function pendingOwner() view returns (address)",
    "function getPublisherOwner(string) view returns (address)",
    "function complianceUploaders(address) view returns (bool)",
  ];
  const registry = new Contract(contractAddress, abi, provider);
  console.log(`Contract: ${explorer}/address/${contractAddress}`);
  console.log(`Runtime code hash: ${runtimeCodeHash}`);
  console.log(`Owner: ${await registry.owner()}; pending owner: ${await registry.pendingOwner()}`);
  if (compliance) console.log(`Compliance authorized: ${await registry.complianceUploaders(compliance.address)}`);
  for (const [name, address] of Object.entries(publishers)) {
    const registered = await registry.getPublisherOwner(name);
    console.log(`Publisher ${name} authorized: ${registered.toLowerCase() === address.toLowerCase()}`);
  }
}

async function deploy(provider, publishers) {
  const deployer = walletFromConfig("BASE_DEPLOYER_PRIVATE_KEY").connect(provider);
  const compliance = walletFromConfig("COMPLIANCE_PRIVATE_KEY");
  if (compliance.address === deployer.address) {
    throw new Error("Use an independent COMPLIANCE_PRIVATE_KEY; the deployer's initial compliance permission is revoked after ownership transfer");
  }
  const desiredOwner = addressFromConfig("BASE_OWNER_ADDRESS") ?? deployer.address;
  const artifactPath = join(root, "artifacts/contracts/TrustedPolicyRegistry.sol/TrustedPolicyRegistry.json");
  const artifact = await readJson(artifactPath);
  if (!artifact?.bytecode || artifact.bytecode === "0x") {
    throw new Error("Compile the current contract first: npm run contract:compile");
  }
  const bytecodeHash = keccak256(artifact.bytecode);
  const saved = await readJson(deploymentPath);
  if (saved) {
    await verifyDeployment(provider, saved, artifact, deployer, compliance, publishers, desiredOwner);
    await writeDeploymentToEnv(saved.contractAddress, saved.deploymentBlock, saved.runtimeCodeHash);
    console.log(`Existing deployment verified: ${explorer}/address/${saved.contractAddress}`);
    return;
  }
  let journal = await readJson(journalPath);
  if (journal && (journal.chainId !== Number(BASE_CHAIN_ID) || journal.bytecodeHash !== bytecodeHash ||
      journal.deployer !== deployer.address || journal.complianceUploader !== compliance.address ||
      journal.desiredOwner !== desiredOwner || !sameAddresses(journal.publisherOwners, publishers))) {
    throw new Error("Pending deployment belongs to a different contract or wallet configuration. Inspect it before retrying.");
  }
  if (!journal && addressFromConfig("CONTRACT_ADDRESS")) {
    throw new Error("CONTRACT_ADDRESS is already configured but no local deployment record exists. Refusing to deploy a second contract.");
  }
  journal ??= {
    chainId: Number(BASE_CHAIN_ID), bytecodeHash, deployer: deployer.address,
    complianceUploader: compliance.address, publisherOwners: publishers,
    desiredOwner, transactions: {},
  };
  const factory = new ContractFactory(artifact.abi, artifact.bytecode, deployer);
  const deploymentRequest = await factory.getDeployTransaction(deployer.address);
  const deploymentReceipt = await sendRecordedTransaction(provider, deployer, journal, "deploy", deploymentRequest);
  const signedDeployment = Transaction.from(journal.transactions.deploy.rawTransaction);
  const contractAddress = getCreateAddress({ from: deployer.address, nonce: signedDeployment.nonce });
  if (deploymentReceipt.contractAddress?.toLowerCase() !== contractAddress.toLowerCase()) {
    throw new Error("Deployment receipt address differs from the signed transaction");
  }
  const registry = new Contract(contractAddress, artifact.abi, deployer);
  const currentOwner = await registry.owner();
  if (currentOwner !== deployer.address && currentOwner !== desiredOwner) {
    throw new Error(`Unexpected owner ${currentOwner} after deployment`);
  }
  for (const [name, address] of Object.entries(publishers)) {
    if ((await registry.getPublisherOwner(name)).toLowerCase() !== address.toLowerCase()) {
      await sendRecordedTransaction(provider, deployer, journal, `publisher:${name}`,
        await registry.setPublisherOwner.populateTransaction(name, address));
      if ((await registry.getPublisherOwner(name)).toLowerCase() !== address.toLowerCase()) {
        throw new Error(`Publisher ${name} authorization was not confirmed`);
      }
    }
  }
  if (!(await registry.complianceUploaders(compliance.address))) {
    await sendRecordedTransaction(provider, deployer, journal, "compliance",
      await registry.setComplianceUploader.populateTransaction(compliance.address, true));
    if (!(await registry.complianceUploaders(compliance.address))) {
      throw new Error("Compliance authorization was not confirmed");
    }
  }
  if (desiredOwner !== deployer.address &&
      (await registry.owner()) !== desiredOwner &&
      (await registry.pendingOwner()) !== desiredOwner) {
    await sendRecordedTransaction(provider, deployer, journal, "owner-transfer",
      await registry.transferOwnership.populateTransaction(desiredOwner));
    if ((await registry.pendingOwner()) !== desiredOwner) {
      throw new Error("Owner transfer proposal was not confirmed");
    }
  }
  const code = await provider.getCode(contractAddress);
  if (code === "0x") throw new Error("Deployed contract bytecode is missing");
  const record = {
    chainId: Number(BASE_CHAIN_ID), contractAddress,
    deployer: deployer.address, desiredOwner,
    complianceUploader: compliance.address, publisherOwners: publishers,
    deploymentTxHash: deploymentReceipt.hash,
    deploymentBlock: deploymentReceipt.blockNumber,
    deploymentBlockHash: deploymentReceipt.blockHash,
    transactionHashes: Object.fromEntries(Object.entries(journal.transactions).map(([phase, value]) => [phase, value.txHash])),
    bytecodeHash, runtimeCodeHash: keccak256(code), deployedAt: new Date().toISOString(),
  };
  await saveJson(deploymentPath, record);
  await writeDeploymentToEnv(contractAddress, deploymentReceipt.blockNumber, record.runtimeCodeHash);
  console.log(`Deployment verified: ${explorer}/address/${contractAddress}`);
  console.log(`Address and deployment block saved to config/base-mainnet.env`);
  if (desiredOwner !== deployer.address) {
    console.log(`Pending owner ${desiredOwner} must call acceptOwnership() to complete the transfer.`);
  }
}

async function main() {
  const command = process.argv[2];
  if (command !== "status" && command !== "deploy") {
    throw new Error("Usage: node scripts/base-mainnet.js status|deploy");
  }
  await loadBaseEnv();
  const publishers = publisherWallets();
  const provider = await connect();
  try {
    if (command === "status") {
      await status(provider, publishers);
      return;
    }
    await mkdir(directory, { recursive: true, mode: 0o700 });
    const lockPath = join(directory, "deploy.lock");
    let lock;
    try {
      lock = await open(lockPath, "wx", 0o600);
    } catch (error) {
      if (error.code === "EEXIST") {
        throw new Error("Another deployment may be running. Inspect data/base-mainnet/deploy.lock and the transaction journal before clearing it.");
      }
      throw error;
    }
    try {
      await lock.writeFile(String(process.pid));
      await deploy(provider, publishers);
    } finally {
      await lock.close();
      await unlink(lockPath);
    }
  } finally {
    provider.destroy();
  }
}

main().catch((error) => {
  console.error(error.shortMessage ?? error.message);
  process.exitCode = 1;
});
