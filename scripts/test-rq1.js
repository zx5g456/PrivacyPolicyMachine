import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtemp, readFile, writeFile, mkdir, rm } from "node:fs/promises";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { JsonRpcProvider, Contract, getBytes } from "ethers";

const root = resolve(new URL("..", import.meta.url).pathname);
const rq1 = join(root, "tests", "rq1");
const outDir = resolve(process.env.RQ1_OUTPUT_DIR ?? join(root, "test-results", "rq1"));
const requirements = JSON.parse(await readFile(join(rq1, "requirements.json"), "utf8"));
const policyV1 = await readFile(join(rq1, "fixtures", "sample-v1.txt"));
const policyV2 = await readFile(join(rq1, "fixtures", "sample-v2.txt"));
const appName = "RQ1 XR Sample";
const developer = "rq1-researcher";
const scenarioNames = {
  S1: "Initial registration",
  S2: "Unclear field in AI extraction",
  S3: "Human correction of an extracted value",
  S4: "Later-version registration",
  S5: "Duplicate registration is rejected",
  S6: "Earlier version remains retrievable and immutable",
  S7: "Modified policy is detected",
};
const scenarioDimensions = {
  S1: "Record construction",
  S2: "Record construction",
  S3: "Record construction",
  S4: "Version management",
  S5: "Integrity protection",
  S6: "Record retrieval",
  S7: "Change detection",
};
const scenarioResults = new Map();
const privateReviewFields = [
  "metadataEvidence", "metadataDetails", "metadataAssessment", "humanReview",
];
const processes = [];
const temp = await mkdtemp(join(tmpdir(), "rq1-e2e-"));
let mockServer;
let provider;
let registry;
let baseUrl;

const listFields = [
  "dataTypeTags", "dataSourceTypes", "collectionContext", "processingPurpose",
  "permittedUsage", "thirdPartySources", "downstreamStakeholders", "thirdPartyPurpose",
  "regulatoryFramework",
];
const statusFields = [
  "sharingCondition", "consentRequired", "optOutAvailable", "deletionAvailable",
  "requestChannel", "retentionPolicy", "encryptionApplied", "anonymisation",
  "crossBorderTransfer", "childDataInvolved", "contactChannel",
];

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function fakeExtraction(policy) {
  const fields = Object.fromEntries(listFields.map((name) => [name, {
    value: [], evidence: {}, details: "", needs_review: false,
  }]));
  for (const name of statusFields) {
    fields[name] = { value: "unclear", evidence: [], details: "", needs_review: true };
  }
  const location = "We collect precise location data during service use to provide the XR experience.";
  const deletion = "You can contact privacy@example.test to request deletion of your account data.";
  const encryption = "We encrypt personal data in transit and at rest.";
  fields.dataTypeTags = {
    value: ["location"], evidence: { location: [location] },
    details: "Precise location is collected during service use.", needs_review: false,
  };
  fields.deletionAvailable = {
    value: "yes", evidence: [deletion], details: "Deletion can be requested.", needs_review: false,
  };
  fields.encryptionApplied = {
    value: "yes", evidence: [encryption], details: "Data is encrypted.", needs_review: false,
  };
  if (policy.includes("device identifiers")) {
    const device = "We also collect device identifiers to prevent fraud and improve account security.";
    fields.dataTypeTags.value.push("device_id");
    fields.dataTypeTags.evidence.device_id = [device];
  }
  return fields;
}

function startFakeOllama() {
  return new Promise((resolveListen) => {
    mockServer = createServer(async (request, response) => {
      const chunks = [];
      for await (const chunk of request) chunks.push(chunk);
      const body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      const prompt = body.messages?.at(-1)?.content ?? "";
      const policy = prompt.split("<policy_chunk>\n")[1]?.split("\n</policy_chunk>")[0] ?? "";
      response.setHeader("content-type", "application/json");
      response.end(JSON.stringify({ message: { content: JSON.stringify(fakeExtraction(policy)) } }));
    });
    mockServer.listen(0, "127.0.0.1", () => resolveListen(mockServer.address().port));
  });
}

async function unusedPort() {
  const server = createServer();
  await new Promise((done) => server.listen(0, "127.0.0.1", done));
  const port = server.address().port;
  await new Promise((done) => server.close(done));
  return port;
}

function launch(label, command, args, env) {
  const child = spawn(command, args, {
    cwd: root, env: { ...process.env, ...env }, detached: process.platform !== "win32",
    stdio: ["ignore", "pipe", "pipe"],
  });
  const entry = { label, child, output: "" };
  for (const stream of [child.stdout, child.stderr]) {
    stream.on("data", (chunk) => { entry.output += chunk.toString(); });
  }
  processes.push(entry);
  return entry;
}

async function run(command, args, env) {
  const entry = launch("deploy", command, args, env);
  const code = await new Promise((done, reject) => {
    entry.child.once("exit", done);
    entry.child.once("error", reject);
  });
  if (code !== 0) throw new Error(`${command} failed (${code}): ${entry.output}`);
  return entry.output;
}

async function waitUntil(probe, label, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try { if (await probe()) return; } catch { /* service is starting */ }
    await delay(200);
  }
  throw new Error(`${label} did not become ready`);
}

async function api(path, form) {
  const response = await fetch(`${baseUrl}${path}`, form ? { method: "POST", body: form } : {});
  const body = await response.json();
  return { status: response.status, body };
}

function formFor(file, fields) {
  const form = new FormData();
  for (const [key, value] of Object.entries(fields)) form.append(key, value);
  form.append("rawFile", new Blob([file], { type: "text/plain" }), "policy.txt");
  return form;
}

function reviewedForm(file, original, reviewed, token, more = {}) {
  return formFor(file, {
    applicationName: appName, developer, metadataJson: JSON.stringify(reviewed),
    originalMetadataJson: JSON.stringify(original), reviewToken: token, ...more,
  });
}

async function countRecords() {
  const result = await api(`/api/policies?applicationName=${encodeURIComponent(appName)}`);
  assert.equal(result.status, 200);
  return result.body.policies.length;
}

async function chainKeys() {
  return registry.getPolicyRecordKeys(developer, appName);
}

async function chainContent(recordKey) {
  const record = await registry.readRecordByKey(recordKey);
  const readChunks = async (count, getter) => {
    const pieces = [];
    for (let index = 0; index < Number(count); index += 1) {
      pieces.push(Buffer.from(getBytes(await getter(recordKey, index))));
    }
    return Buffer.concat(pieces);
  };
  const raw = await readChunks(record.documentChunkCount, registry.readDocumentChunk);
  const metadataBytes = await readChunks(record.metadataChunkCount, registry.readMetadataChunk);
  return { raw, metadata: JSON.parse(metadataBytes.toString("utf8")) };
}

function scenario(id, checks, evidence = {}, error = "") {
  const result = {
    id, name: scenarioNames[id], dimension: scenarioDimensions[id],
    passed: !error && Object.values(checks).every(Boolean), checks, evidence,
    ...(error ? { error } : {}),
  };
  scenarioResults.set(id, result);
  console.log(`${result.passed ? "PASS" : "FAIL"} ${id} ${result.name}`);
  return result;
}

function completeness(records) {
  const required = [
    "policyId", "policyVersion", "applicationName", "developer", "documentHash",
    "publisherEntity", "serviceName", "uploadMethod", "metadataEvidence",
    "metadataDetails", "metadataAssessment", "humanReview",
    ...listFields, ...statusFields,
  ];
  const checks = records.flatMap((record) => required.map((field) => ({
    recordKey: record.recordKey, field,
    valid: Object.hasOwn(record.metadata, field) && record.metadata[field] !== null &&
      record.metadata[field] !== "",
  })));
  return { numerator: checks.filter((check) => check.valid).length, denominator: checks.length, checks };
}

function traceLinks(records, versionLink) {
  const links = [];
  for (const record of records) {
    const evidence = record.metadata.metadataEvidence ?? {};
    for (const field of [...listFields, ...statusFields]) {
      const value = record.metadata[field];
      const byValue = evidence[field];
      if (Array.isArray(value)) {
        for (const item of value) {
          const quotes = byValue?.[item] ?? [];
          links.push({ recordKey: record.recordKey, field, value: item,
            valid: quotes.length > 0 && quotes.every((quote) => record.raw.includes(quote)) });
        }
      } else if (value === "yes" || value === "no") {
        links.push({ recordKey: record.recordKey, field, value,
          valid: Array.isArray(byValue) && byValue.length > 0 &&
            byValue.every((quote) => record.raw.includes(quote)) });
      }
    }
  }
  links.push(versionLink);
  return { numerator: links.filter((link) => link.valid).length, denominator: links.length, links };
}

function ratio(measure) {
  return measure.denominator ? measure.numerator / measure.denominator : null;
}

async function main() {
  await mkdir(outDir, { recursive: true });
  const mockPort = await startFakeOllama();
  const rpcPort = await unusedPort();
  const appPort = await unusedPort();
  const rpcUrl = `http://127.0.0.1:${rpcPort}`;
  baseUrl = `http://127.0.0.1:${appPort}`;

  launch("hardhat", "npm", ["run", "chain", "--", "--port", String(rpcPort)], {});
  await waitUntil(async () => {
    const response = await fetch(rpcUrl, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "eth_chainId", params: [] }),
    });
    return Number((await response.json()).result) === 31337;
  }, "Hardhat RPC");
  provider = new JsonRpcProvider(rpcUrl);
  const deployOutput = await run(process.execPath, ["scripts/deploy-contract.js"], { RPC_URL: rpcUrl });
  const address = deployOutput.match(/TrustedPolicyRegistry deployed to:\s*(0x[a-fA-F0-9]{40})/)?.[1];
  assert.ok(address, `Deployment address missing: ${deployOutput}`);
  const artifact = JSON.parse(await readFile(
    join(root, "artifacts", "contracts", "TrustedPolicyRegistry.sol", "TrustedPolicyRegistry.json"), "utf8",
  ));
  registry = new Contract(address, artifact.abi, provider);
  launch("api", join(root, ".venv", "bin", "python"), ["-m", "server.app"], {
    RPC_URL: rpcUrl, CONTRACT_ADDRESS: address, CONTRACT_DEPLOYMENT_BLOCK: "1",
    POLICY_DB_PATH: join(temp, "policies.db"),
    OLLAMA_CHAT_URL: `http://127.0.0.1:${mockPort}/api/chat`,
    OLLAMA_RETRIES: "0", PORT: String(appPort),
  });
  await waitUntil(async () => (await api("/api/policies")).status === 200, "API server");

  const preview1 = await api("/api/analyze", formFor(policyV1, { applicationName: appName, developer }));
  const draft1 = preview1.body.metadata;
  const s2Checks = {
    analysisSucceeded: preview1.status === 200,
    explicitlyUnclear: draft1?.retentionPolicy === "unclear",
    reviewFlagged: draft1?.metadataAssessment?.retentionPolicy?.reviewStatus === "needs_review",
    notPersisted: (await countRecords()) === 0 && (await chainKeys()).length === 0,
  };
  scenario("S2", s2Checks, { policyId: draft1?.policyId });

  const reviewed1 = structuredClone(draft1);
  const retentionQuote = "We retain account records for seven years.";
  reviewed1.retentionPolicy = "yes";
  reviewed1.metadataEvidence.retentionPolicy = [retentionQuote];
  reviewed1.metadataDetails.retentionPolicy = "Account records are retained for seven years.";
  reviewed1.riskFlags = reviewed1.riskFlags.filter((flag) => flag !== "unclear_retention");
  const invalidReview = await api("/api/policies/reviewed", reviewedForm(
    policyV1, draft1, reviewed1, "invalid-signature",
  ));
  const fabricated = structuredClone(reviewed1);
  fabricated.metadataEvidence.retentionPolicy = ["We retain account records forever."];
  const invalidEvidence = await api("/api/policies/reviewed", reviewedForm(
    policyV1, draft1, fabricated, preview1.body.reviewToken,
  ));
  const registration1 = await api("/api/policies/reviewed", reviewedForm(
    policyV1, draft1, reviewed1, preview1.body.reviewToken,
  ));
  const first = registration1.body;
  const firstKey = first.onChain?.recordKey;
  const review = first.metadata?.humanReview;
  scenario("S3", {
    forgedDraftRejected: invalidReview.status === 400,
    fabricatedEvidenceRejected: invalidEvidence.status === 400,
    editRegistered: registration1.status === 201,
    fieldMarked: first.metadata?.metadataAssessment?.retentionPolicy?.reviewStatus === "human_edited",
    beforeAfterRecorded: review?.changes?.retentionPolicy?.before?.value === "unclear" &&
      review?.changes?.retentionPolicy?.after?.value === "yes",
    evidencePreserved: review?.changes?.retentionPolicy?.after?.evidence?.includes(retentionQuote),
  }, { recordKey: firstKey, txHash: first.onChain?.txHash });

  const audit1 = firstKey ? await api(`/api/audit/${firstKey}`) : { body: {} };
  const chainFirst = firstKey ? await registry.readRecordByKey(firstKey) : null;
  const firstContent = firstKey ? await chainContent(firstKey) : null;
  scenario("S1", {
    sqlRecordCreated: first.policy?.policyId === draft1.policyId && (await countRecords()) === 1,
    chainRecordCreated: Boolean(chainFirst),
    documentHashMatches: first.onChain?.data?.documentHash === `0x${sha256(policyV1)}`,
    chainAuditValid: audit1.body.valid === true,
    allAuditChecksPass: Object.values(audit1.body.checks ?? {}).every(Boolean),
    initialHasNoPredecessor: first.onChain?.data?.hasPreviousReference === false,
    reviewInformationAbsentOnChain: firstContent && privateReviewFields.every(
      (field) => !Object.hasOwn(firstContent.metadata, field)
    ) && !firstContent.metadata.riskFlags?.includes("review_recommended"),
    finalValuePresentOnChain: firstContent?.metadata?.retentionPolicy === "yes",
  }, { recordKey: firstKey, txHash: first.onChain?.txHash, audit: audit1.body.checks });

  const preview2 = await api("/api/analyze", formFor(policyV2, {
    applicationName: appName, developer, policyId: draft1.policyId,
  }));
  const draft2 = preview2.body.metadata;
  const registration2 = await api("/api/policies/update", reviewedForm(
    policyV2, draft2, draft2, preview2.body.reviewToken,
    { policyId: draft1.policyId, changeSummary: "Added device identifiers for security." },
  ));
  const second = registration2.body;
  const secondKey = second.onChain?.recordKey;
  const latest = secondKey ? await registry.readLatestOnChainRecord(developer, appName) : null;
  const secondContent = secondKey ? await chainContent(secondKey) : null;
  scenario("S4", {
    laterVersionRegistered: registration2.status === 201,
    newRecordKey: firstKey !== secondKey,
    predecessorLinked: second.onChain?.data?.previousRecordKey?.toLowerCase() === firstKey?.toLowerCase(),
    latestIsSecond: latest?.[14]?.toLowerCase() === firstKey?.toLowerCase() &&
      second.onChain?.data?.policyVersion === draft2?.policyVersion,
    twoSqlAndChainRecords: (await countRecords()) === 2 && (await chainKeys()).length === 2,
    reviewInformationAbsentOnChain: secondContent && privateReviewFields.every(
      (field) => !Object.hasOwn(secondContent.metadata, field)
    ) && !secondContent.metadata.riskFlags?.includes("review_recommended"),
    finalValuesPresentOnChain: secondContent?.metadata?.dataTypeTags?.includes("device_id"),
  }, { recordKey: secondKey, previousRecordKey: firstKey, txHash: second.onChain?.txHash });

  const beforeDuplicate = { sql: await countRecords(), chain: (await chainKeys()).length };
  const duplicate = await api("/api/policies/update", reviewedForm(
    policyV1, draft1, reviewed1, preview1.body.reviewToken, { policyId: draft1.policyId },
  ));
  scenario("S5", {
    duplicateRejected: duplicate.status === 409,
    sqlUnchanged: (await countRecords()) === beforeDuplicate.sql,
    chainUnchanged: (await chainKeys()).length === beforeDuplicate.chain,
  }, { httpStatus: duplicate.status, error: duplicate.body.error });

  const firstByVersion = await registry.readOnChainRecord(developer, appName, draft1.policyVersion);
  const firstAfter = await registry.readRecordByKey(firstKey);
  const firstAuditAfter = await api(`/api/audit/${firstKey}`);
  const secondAudit = await api(`/api/audit/${secondKey}`);
  const records = (await api(`/api/policies?applicationName=${encodeURIComponent(appName)}`)).body.policies;
  scenario("S6", {
    oldVersionResolves: firstByVersion?.[0] === first.onChain.data.documentHash,
    oldRecordImmutable: firstAfter?.[0] === chainFirst?.[0] &&
      firstAfter?.[1] === chainFirst?.[1],
    oldVersionStillAudits: firstAuditAfter.body.valid === true,
    currentVersionAudits: secondAudit.body.valid === true,
    bothVersionsInSql: records.some((item) => item.policyVersion === draft1.policyVersion) &&
      records.some((item) => item.policyVersion === draft2.policyVersion),
  }, { oldRecordKey: firstKey, oldAudit: firstAuditAfter.body.checks,
    currentAudit: secondAudit.body.checks });

  const valid = await api("/api/verify", formFor(policyV2, { applicationName: appName }));
  const tampered = Buffer.from(policyV2.toString("utf8").replace("prevent fraud", "profile users"));
  const modified = await api("/api/verify", formFor(tampered, { applicationName: appName }));
  scenario("S7", {
    originalAccepted: valid.body.verified === true,
    publicMetadataMode: valid.body.metadataStorageMode === "governance_only",
    modifiedRejected: modified.body.verified === false,
    exactHashMismatchIdentified: modified.body.comparisons?.submittedHashMatchesSql === false,
    chainHashMismatchIdentified: modified.body.comparisons?.submittedHashMatchesOnChainContent === false,
  }, { originalHash: valid.body.submittedHash, modifiedHash: modified.body.submittedHash,
    failedComparisons: Object.entries(modified.body.comparisons ?? {}).filter(([, pass]) => !pass).map(([name]) => name) });

  const storedContents = [firstContent, secondContent];
  const recordInputs = [first, second].map((item, index) => ({
    recordKey: item.onChain.recordKey,
    metadata: item.metadata,
    raw: storedContents[index].raw.toString("utf8"),
  }));
  const complete = completeness(recordInputs);
  const links = traceLinks(recordInputs, {
    type: "version", from: secondKey, to: firstKey,
    valid: second.onChain.data.previousRecordKey.toLowerCase() === firstKey.toLowerCase(),
  });
  const scenarios = Object.keys(scenarioNames).map((id) => scenarioResults.get(id));
  const dimensions = [...new Set(requirements.requirements.map((item) => item.dimension))].map((name) => {
    const relatedIds = [...new Set(requirements.requirements
      .filter((item) => item.dimension === name)
      .flatMap((item) => item.scenarioIds))];
    const related = relatedIds.map((id) => scenarioResults.get(id));
    return {
      name, scenarioIds: related.map((item) => item.id),
      passed: related.every((item) => item.passed),
      evidence: [...new Set(related.flatMap((item) => [
        item.evidence.recordKey, item.evidence.oldRecordKey,
        item.evidence.originalHash, item.evidence.modifiedHash,
      ].filter(Boolean)))],
    };
  });
  const reqResults = requirements.requirements.map((requirement) => ({
    ...requirement,
    demonstrated: requirement.scenarioIds.every((id) => scenarioResults.get(id)?.passed),
  }));
  const coverage = { numerator: reqResults.filter((item) => item.demonstrated).length,
    denominator: reqResults.length };
  const passed = { numerator: scenarios.filter((item) => item.passed).length,
    denominator: scenarios.length };
  const report = {
    generatedAt: new Date().toISOString(),
    fixture: "one deterministic synthetic XR policy family with two versions",
    model: "deterministic local Ollama-compatible stub; not an RQ3 accuracy evaluation",
    chainId: 31337, contractAddress: address,
    excludedScenario: requirements.excludedScenario,
    exclusionReason: requirements.exclusionReason,
    requirements: reqResults, scenarios, dimensions,
    measures: {
      requirementCoverage: { ...coverage, value: ratio(coverage) },
      scenarioPassRate: { ...passed, value: ratio(passed) },
      recordCompleteness: { ...complete, value: ratio(complete) },
      traceLinkCorrectness: { ...links, value: ratio(links) },
    },
  };
  await writeFile(join(outDir, "rq1-results.json"), JSON.stringify(report, null, 2) + "\n");
  const percent = (measure) => `${(measure.value * 100).toFixed(1)}% (${measure.numerator}/${measure.denominator})`;
  const short = (value) => value.length > 22 ? `${value.slice(0, 12)}...${value.slice(-6)}` : value;
  const markdown = [
    "# RQ1 automated evaluation summary", "",
    `Generated: ${report.generatedAt}`, "",
    `Scope: ${report.fixture}; ${report.model}. Human review is simulated by a deterministic correction.`, "",
    `Excluded: ${report.excludedScenario}. ${report.exclusionReason}`, "",
    "## Overall measures", "",
    "| Measure | Result |", "| --- | ---: |",
    `| Requirement coverage | ${percent(report.measures.requirementCoverage)} |`,
    `| Scenario pass rate | ${percent(report.measures.scenarioPassRate)} |`,
    `| Record completeness | ${percent(report.measures.recordCompleteness)} |`,
    `| Trace-link correctness | ${percent(report.measures.traceLinkCorrectness)} |`,
    "", "## Evaluation dimensions", "",
    "| Dimension | Scenarios | Actual result | Evidence |",
    "| --- | --- | --- | --- |",
    ...dimensions.map((item) => `| ${item.name} | ${item.scenarioIds.join(", ")} | ${item.passed ? "PASS" : "FAIL"} | ${item.evidence.map(short).join(", ") || "See detailed assertions"} |`),
    "", "## Scenario results", "",
    "| ID | Dimension | Scenario | Result |", "| --- | --- | --- | --- |",
    ...scenarios.map((item) => `| ${item.id} | ${item.dimension} | ${item.name} | ${item.passed ? "PASS" : "FAIL"} |`),
    "", "Full assertions, transaction hashes, record keys, and denominators are in `rq1-results.json`.", "",
  ].join("\n");
  await writeFile(join(outDir, "rq1-summary.md"), markdown);
  if (passed.numerator !== passed.denominator || coverage.numerator !== coverage.denominator ||
      complete.numerator !== complete.denominator || links.numerator !== links.denominator) {
    process.exitCode = 1;
  }
  console.log(`RQ1 report: ${outDir}`);
}

try {
  await main();
} catch (error) {
  process.exitCode = 1;
  console.error(error);
  await mkdir(outDir, { recursive: true });
  await writeFile(join(outDir, "rq1-failure.txt"), `${error.stack ?? error}\n`);
} finally {
  for (const { child } of processes.reverse()) {
    if (child.exitCode !== null) continue;
    try {
      if (process.platform === "win32") child.kill("SIGTERM");
      else process.kill(-child.pid, "SIGTERM");
    } catch { /* already exited */ }
  }
  if (mockServer) await new Promise((done) => mockServer.close(done));
  if (provider) provider.destroy();
  await rm(temp, { recursive: true, force: true });
}
