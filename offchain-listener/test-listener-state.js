import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { loadState } from "./listener-state.js";

const deploymentBlock = 53266737;
const deploymentHash = `0x${"12".repeat(32)}`;
const currentIdentity = [
  "8453",
  "0x365951acb47e61edf0a7d65f5e4150bb22f9bcc7",
  deploymentBlock,
  deploymentHash,
].join(":");
const oldIdentity = ["8453", `0x${"ab".repeat(32)}`, ...currentIdentity.split(":").slice(1)].join(":");

test("migrates matching legacy listener state without replaying its cursor", async () => {
  const directory = await mkdtemp(join(tmpdir(), "listener-state-"));
  try {
    const path = join(directory, "state.json");
    const existing = {
      chainIdentity: oldIdentity,
      lastProcessedBlock: deploymentBlock + 1200,
      processedEvents: { "0xevent:0": deploymentBlock + 1000 },
      invalidEvents: { "0xinvalid:0": { reason: "invalid policy" } },
    };
    await writeFile(path, JSON.stringify(existing));

    const loaded = await loadState(path, deploymentBlock - 1, deploymentBlock + 2000, currentIdentity);
    assert.deepEqual(loaded, { ...existing, chainIdentity: currentIdentity });

    const wrongDeploymentIdentity = currentIdentity.replace(deploymentHash, `0x${"34".repeat(32)}`);
    const reset = await loadState(path, deploymentBlock - 1, deploymentBlock + 2000, wrongDeploymentIdentity);
    assert.deepEqual(reset, {
      chainIdentity: wrongDeploymentIdentity,
      lastProcessedBlock: deploymentBlock - 1,
      processedEvents: {},
      invalidEvents: {},
    });
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
