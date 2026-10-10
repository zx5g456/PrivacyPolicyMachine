import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { join } from "node:path";
import {
  Contract, ContractFactory, FetchRequest, JsonRpcProvider, Transaction,
  Wallet, formatEther, getCreateAddress, keccak256,
} from "ethers";

const root = fileURLToPath(new URL("../", import.meta.url));
const directory = join(root, "data", "base-sepolia");
const walletPath = join(directory, "wallet.json");
const deploymentPath = join(directory, "deployment.json");
const journalPath = join(directory, "pending-transactions.json");
const chainId = 84532;
const explorer = "https://sepolia.basescan.org";

async function readJson(path) {
  try {
    return JSON.parse(await readFile(path, "utf8"));
  } catch (error) {
    if (error.code === "ENOENT") return null;
    throw error;
  }
}

async function saveJson(path, value) {
  const temporary = `${path}.${process.pid}.tmp`;
  await writeFile(temporary, JSON.stringify(value, null, 2) + "\n", { mode: 0o600 });
  await rename(temporary, path);
}

async function loadWallets(create = false) {
  await mkdir(directory, { recursive: true, mode: 0o700 });
  let saved = await readJson(walletPath);
  if (!saved && create) {
    const deployer = Wallet.createRandom();
    const compliance = Wallet.createRandom();
    saved = {
      chainId,
      deployer: { address: deployer.address, privateKey: deployer.privateKey },
      compliance: { address: compliance.address, privateKey: compliance.privateKey },
    };
    // Exclusive creation prevents accidentally replacing an existing funded wallet.
    await writeFile(walletPath, JSON.stringify(saved, null, 2) + "\n", { flag: "wx", mode: 0o600 });
  }
  if (!saved) throw new Error("Run npm run sepolia:wallet first.");
  try {
    const deployer = new Wallet(saved.deployer.privateKey);
    const compliance = new Wallet(saved.compliance.privateKey);
    if (saved.chainId !== chainId || deployer.address !== saved.deployer.address || compliance.address !== saved.compliance.address) {
      throw new Error("Wallet metadata mismatch");
    }
    return { deployer, compliance };
  } catch {
    throw new Error("The local test wallet file is invalid; do not replace a funded wallet.");
  }
}

async function sendRecordedTransaction(provider, signer, journal, phase, request) {
  let entry = journal[phase];
  if (!entry) {
    const nonce = Number(await provider.send("eth_getTransactionCount", [signer.address, "pending"]));
    const populated = await signer.populateTransaction({ ...request, nonce });
    const rawTransaction = await signer.signTransaction(populated);
    entry = { txHash: Transaction.from(rawTransaction).hash, rawTransaction };
    journal[phase] = entry;
    // Save the signed transaction before broadcasting so interrupted runs reuse it.
    await saveJson(journalPath, journal);
  }
  const transaction = Transaction.from(entry.rawTransaction);
  if (transaction.hash !== entry.txHash || transaction.chainId !== BigInt(chainId) || transaction.from !== signer.address) {
    throw new Error(`Invalid ${phase} transaction journal.`);
  }
  let receipt = await provider.getTransactionReceipt(entry.txHash);
  if (!receipt && !(await provider.getTransaction(entry.txHash))) {
    await provider.broadcastTransaction(entry.rawTransaction);
  }
  console.log(`${phase}: ${explorer}/tx/${entry.txHash}`);
  receipt ??= await provider.waitForTransaction(entry.txHash, 1, 180_000);
  if (!receipt) throw new Error("Confirmation timed out. Rerun the same command to resume.");
  if (receipt.status !== 1) throw new Error(`${phase} reverted. Inspect the saved transaction before retrying.`);
  return receipt;
}

async function deploy(provider, wallets) {
  const artifact = await readJson(join(root, "artifacts/contracts/TrustedPolicyRegistry.sol/TrustedPolicyRegistry.json"));
  if (!artifact?.bytecode || artifact.bytecode === "0x") throw new Error("Run npm run contract:compile first.");
  const bytecodeHash = keccak256(artifact.bytecode);
  const signer = wallets.deployer.connect(provider);
  const previous = await readJson(deploymentPath);
  if (previous) {
    if (previous.chainId !== chainId || previous.bytecodeHash !== bytecodeHash || previous.owner !== signer.address || previous.complianceUploader !== wallets.compliance.address) {
      throw new Error("Saved deployment differs from this contract or wallet. Refusing to redeploy automatically.");
    }
    const contract = new Contract(previous.contractAddress, artifact.abi, provider);
    const receipt = await provider.getTransactionReceipt(previous.deploymentTxHash);
    const code = await provider.getCode(previous.contractAddress);
    if (!receipt || receipt.status !== 1 || receipt.blockHash !== previous.deploymentBlockHash || code === "0x" || keccak256(code) !== previous.runtimeCodeHash || await contract.owner() !== signer.address || !(await contract.complianceUploaders(wallets.compliance.address))) {
      throw new Error("Saved deployment could not be verified on the current network.");
    }
    console.log(`Existing deployment verified: ${explorer}/address/${previous.contractAddress}`);
    return;
  }

  let journal = await readJson(journalPath);
  if (journal && (journal.chainId !== chainId || journal.bytecodeHash !== bytecodeHash || journal.owner !== signer.address || journal.complianceUploader !== wallets.compliance.address)) {
    throw new Error("Pending deployment uses a different contract or wallet. Inspect it before retrying.");
  }
  journal ??= { chainId, bytecodeHash, owner: signer.address, complianceUploader: wallets.compliance.address };
  const factory = new ContractFactory(artifact.abi, artifact.bytecode, signer);
  let request = await factory.getDeployTransaction();
  if (!journal.deploy) {
    const balance = await provider.getBalance(signer.address);
    if (balance === 0n) throw new Error(`Fund ${signer.address} with Base Sepolia test ETH first.`);
    const gas = await signer.estimateGas(request);
    const fees = await provider.getFeeData();
    const gasPrice = fees.maxFeePerGas ?? fees.gasPrice;
    if (gasPrice == null) throw new Error("RPC did not return a gas price.");
    const gasLimit = gas * 120n / 100n;
    const executionFee = gasLimit * gasPrice;
    console.log(`Deployment gas estimate: ${gas}; execution fee ceiling: ${formatEther(executionFee)} test ETH (L1 data fee and authorization are additional).`);
    if (balance < executionFee) throw new Error(`Insufficient deployment balance for ${signer.address}: ${formatEther(balance)} test ETH.`);
    request = { ...request, gasLimit };
  }
  const deployed = await sendRecordedTransaction(provider, signer, journal, "deploy", request);
  const signedDeployment = Transaction.from(journal.deploy.rawTransaction);
  const address = getCreateAddress({ from: signer.address, nonce: signedDeployment.nonce });
  if (deployed.contractAddress !== address) throw new Error("Deployment receipt address does not match the signed transaction.");
  const contract = new Contract(address, artifact.abi, signer);
  if (await contract.owner() !== signer.address) throw new Error("Contract owner does not match the deployer.");
  if (!(await contract.complianceUploaders(wallets.compliance.address))) {
    const authorize = await contract.setComplianceUploader.populateTransaction(wallets.compliance.address, true);
    await sendRecordedTransaction(provider, signer, journal, "authorize", authorize);
  }
  if (!(await contract.complianceUploaders(wallets.compliance.address))) throw new Error("Compliance authorization was not confirmed.");
  const code = await provider.getCode(address);
  if (code === "0x") throw new Error("Deployed contract code is missing.");
  const saved = {
    chainId, contractAddress: address, owner: signer.address,
    complianceUploader: wallets.compliance.address,
    deploymentTxHash: deployed.hash, deploymentBlock: deployed.blockNumber,
    deploymentBlockHash: deployed.blockHash, authorizationTxHash: journal.authorize?.txHash,
    bytecodeHash, runtimeCodeHash: keccak256(code), deployedAt: new Date().toISOString(),
  };
  await saveJson(deploymentPath, saved);
  console.log(`Deployment verified: ${explorer}/address/${address}`);
  console.log(`CONTRACT_ADDRESS=${address}\nCONTRACT_DEPLOYMENT_BLOCK=${deployed.blockNumber}`);
  console.log(`Deployment record saved to ${deploymentPath}`);
}

async function main() {
  const command = process.argv[2];
  if (!["wallet", "status", "deploy"].includes(command)) throw new Error("Usage: node scripts/base-sepolia.js wallet|status|deploy");
  const wallets = await loadWallets(command === "wallet");
  console.log(`Network: Base Sepolia (${chainId})`);
  console.log(`Deployer / policy uploader: ${wallets.deployer.address}`);
  console.log(`Compliance uploader: ${wallets.compliance.address}`);
  if (command === "wallet") {
    console.log(`Private keys saved locally at ${walletPath} (owner-only access, excluded from Git).`);
    return;
  }
  const connection = new FetchRequest(process.env.BASE_SEPOLIA_RPC_URL || "https://sepolia.base.org");
  connection.timeout = 20_000;
  const provider = new JsonRpcProvider(connection, undefined, { batchMaxCount: 1 });
  try {
    const network = await provider.getNetwork();
    if (network.chainId !== BigInt(chainId)) throw new Error(`Expected Base Sepolia chain ${chainId}; connected to ${network.chainId}. No transaction sent.`);
    const balances = await Promise.all([
      provider.getBalance(wallets.deployer.address), provider.getBalance(wallets.compliance.address),
    ]);
    console.log(`Deployer balance: ${formatEther(balances[0])} test ETH`);
    console.log(`Compliance balance: ${formatEther(balances[1])} test ETH`);
    if (command === "deploy") {
      // The lock stops concurrent invocations from sending duplicate deployments.
      const lockPath = join(directory, "deploy.lock");
      const { open, unlink } = await import("node:fs/promises");
      let lock;
      try {
        lock = await open(lockPath, "wx", 0o600);
      } catch (error) {
        if (error.code === "EEXIST") throw new Error("Deployment is locked. Check for another running deployment before clearing deploy.lock.");
        throw error;
      }
      try {
        await lock.writeFile(String(process.pid));
        await deploy(provider, wallets);
      } finally {
        await lock.close();
        await unlink(lockPath);
      }
    }
  } finally {
    provider.destroy();
  }
}

main().catch((error) => {
  console.error(error.shortMessage || error.message);
  process.exitCode = 1;
});
