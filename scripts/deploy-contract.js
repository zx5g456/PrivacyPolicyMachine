import { readFile } from "node:fs/promises";
import { ContractFactory, JsonRpcProvider } from "ethers";

const rpcUrl = process.env.RPC_URL ?? "http://127.0.0.1:8545";
const artifactUrl = new URL(
  "../artifacts/contracts/TrustedPolicyRegistry.sol/TrustedPolicyRegistry.json",
  import.meta.url,
);

let artifact;
try {
  artifact = JSON.parse(await readFile(artifactUrl, "utf8"));
} catch (error) {
  if (error.code === "ENOENT") {
    console.error("Contract artifact not found. Run `npm run contract:compile` first.");
    process.exit(1);
  }
  throw error;
}

const provider = new JsonRpcProvider(rpcUrl);
const signer = await provider.getSigner(0);
const factory = new ContractFactory(artifact.abi, artifact.bytecode, signer);
const registry = await factory.deploy();

await registry.waitForDeployment();
const contractAddress = await registry.getAddress();
const deploymentTransaction = registry.deploymentTransaction();
const deploymentReceipt = await deploymentTransaction.wait();
const configuredComplianceUploader = process.env.COMPLIANCE_UPLOADER_ACCOUNT;
const complianceUploaderAddress = configuredComplianceUploader
  ? /^\d+$/.test(configuredComplianceUploader)
    ? await (await provider.getSigner(Number.parseInt(configuredComplianceUploader, 10))).getAddress()
    : configuredComplianceUploader
  : await signer.getAddress();
if (complianceUploaderAddress.toLowerCase() !== (await signer.getAddress()).toLowerCase()) {
  const authorization = await registry.setComplianceUploader(
    complianceUploaderAddress,
    true,
  );
  await authorization.wait();
  console.log(`Authorized compliance uploader: ${complianceUploaderAddress}`);
}

console.log(`TrustedPolicyRegistry deployed to: ${contractAddress}`);
console.log("Use these values in the other terminals:");
console.log(`export RPC_URL=${rpcUrl}`);
console.log(`export CONTRACT_ADDRESS=${contractAddress}`);
console.log(`export CONTRACT_DEPLOYMENT_BLOCK=${deploymentReceipt.blockNumber}`);

provider.destroy();
