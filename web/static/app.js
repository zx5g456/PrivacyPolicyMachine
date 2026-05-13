const policyForm = document.querySelector("#policyForm");
const queryForm = document.querySelector("#queryForm");
const verifyForm = document.querySelector("#verifyForm");
const updateForm = document.querySelector("#updateForm");
const sampleButton = document.querySelector("#sampleButton");
const refreshButton = document.querySelector("#refreshButton");
const developerSelect = document.querySelector("#developerSelect");
const managedPolicySelect = document.querySelector("#managedPolicySelect");
const readinessMetric = document.querySelector("#readinessMetric");
const hashValue = document.querySelector("#hashValue");
const txValue = document.querySelector("#txValue");
const storageValue = document.querySelector("#storageValue");
const blockValue = document.querySelector("#blockValue");
const reportBox = document.querySelector("#reportBox");
const queryBox = document.querySelector("#queryBox");
const queryFullText = document.querySelector("#queryFullText");
const verificationBox = document.querySelector("#verificationBox");
const updateBox = document.querySelector("#updateBox");
const selectedPolicyBox = document.querySelector("#selectedPolicyBox");
const recordList = document.querySelector("#recordList");
const recordCount = document.querySelector("#recordCount");
const manageableCount = document.querySelector("#manageableCount");
const systemStatus = document.querySelector("#systemStatus");
let manageablePolicies = [];
let listedPolicies = [];

const samplePolicy = `PRIVACY POLICY:
We collect personal information including name and email when users create an account.
We share limited data with third party vendors that provide hosting and analytics.
We retain records only for the storage period required to provide the service.
Users may access, correct, delete, or opt out of certain processing activities.
We use security safeguards including encryption and access controls.`;

sampleButton.addEventListener("click", () => {
  const sampleFile = new File([samplePolicy], "sample-privacy-policy.txt", { type: "text/plain" });
  const transfer = new DataTransfer();
  transfer.items.add(sampleFile);
  policyForm.rawFile.files = transfer.files;
  policyForm.applicationName.value = "Sample Privacy App";
});

refreshButton.addEventListener("click", () => loadRecords());
managedPolicySelect.addEventListener("change", () => syncSelectedPolicy());
developerSelect.addEventListener("change", () => {
  syncDeveloperFields();
  loadRecords(queryForm.applicationName.value.trim());
});

policyForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  syncDeveloperFields();
  if (!policyForm.applicationName.value.trim()) {
    reportBox.textContent = "Please enter an application name.";
    policyForm.applicationName.focus();
    return;
  }
  const payload = new FormData(policyForm);
  setBusy(true);
  try {
    const result = await postForm("/api/policies", payload);
    renderProcessingResult(result);
    if (policyForm.rawFile.files.length) {
      const transfer = new DataTransfer();
      transfer.items.add(policyForm.rawFile.files[0]);
      verifyForm.rawFile.files = transfer.files;
    }
    verifyForm.applicationName.value = result.policy.policy_name;
    await loadRecords();
    managedPolicySelect.value = result.policy.policy_id;
    syncSelectedPolicy();
  } catch (error) {
    reportBox.textContent = formatError(error);
  } finally {
    setBusy(false);
  }
});

queryForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const applicationName = queryForm.applicationName.value.trim();
  if (!applicationName) {
    queryBox.className = "verification fail";
    queryBox.textContent = "Please enter an application name to query.";
    queryForm.applicationName.focus();
    return;
  }
  setBusy(true);
  try {
    await loadRecords(applicationName);
    queryBox.className = "verification pass";
    if (listedPolicies.length) {
      renderQueryFullText(listedPolicies[0]);
      verifyForm.applicationName.value = displayPolicyName(listedPolicies[0]);
      queryBox.textContent = `Showing ${listedPolicies.length} record(s). Full text below is the latest match.`;
    } else {
      queryFullText.textContent = "No matching policy found.";
      queryBox.textContent = `No records found for application name: ${applicationName}`;
    }
  } catch (error) {
    queryBox.className = "verification fail";
    queryBox.textContent = formatError(error);
  } finally {
    setBusy(false);
  }
});

verifyForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!verifyForm.applicationName.value.trim()) {
    verificationBox.className = "verification fail";
    verificationBox.textContent = "Please enter the application name to verify.";
    verifyForm.applicationName.focus();
    return;
  }
  if (!verifyForm.rawFile.files.length && !verifyForm.rawText.value.trim()) {
    verificationBox.className = "verification fail";
    verificationBox.textContent = "Upload a policy file or paste policy text to verify.";
    verifyForm.rawText.focus();
    return;
  }
  const payload = new FormData(verifyForm);
  setBusy(true);
  try {
    const result = await postForm("/api/verify", payload);
    renderVerification(result);
  } catch (error) {
    verificationBox.className = "verification fail";
    verificationBox.textContent = formatError(error);
  } finally {
    setBusy(false);
  }
});

updateForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  syncDeveloperFields();
  if (!updateForm.policyId.value.trim()) {
    updateBox.className = "verification fail";
    updateBox.textContent = "Please select a policy to update.";
    managedPolicySelect.focus();
    return;
  }
  if (!updateForm.rawFile.files.length) {
    updateBox.className = "verification fail";
    updateBox.textContent = "Please upload a new policy file before updating.";
    updateForm.rawFile.focus();
    return;
  }
  const payload = new FormData(updateForm);
  setBusy(true);
  try {
    const result = await postForm("/api/policies/update", payload);
    renderProcessingResult(result);
    updateBox.className = "verification pass";
    updateBox.textContent = [
      result.message,
      `Policy ID: ${result.policy.policy_id}`,
      `Application Name: ${result.policy.policy_name}`,
      `Developer: ${result.policy.developer_name}`,
      `Uploaded: ${result.policy.policy_version}`,
      `Hash: ${shorten(result.policy.hash_code)}`,
    ].join("\n");
    await loadRecords();
    managedPolicySelect.value = result.policy.policy_id;
    syncSelectedPolicy();
  } catch (error) {
    updateBox.className = "verification fail";
    updateBox.textContent = formatError(error);
  } finally {
    setBusy(false);
  }
});

async function postForm(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    body: payload,
  });
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.error || data.reason || "Request failed");
    error.details = data;
    throw error;
  }
  return data;
}

recordList.addEventListener("click", (event) => {
  const button = event.target.closest("[data-use-record]");
  if (!button) {
    return;
  }
  const policy = listedPolicies.find((item) => String(item.id) === button.dataset.recordId);
  if (policy) {
    verifyForm.rawText.value = policy.raw_file;
    verifyForm.rawFile.value = "";
    verifyForm.applicationName.value = displayPolicyName(policy);
    renderQueryFullText(policy);
  }
  verificationBox.className = "verification";
  verificationBox.textContent = "Record content loaded for verification.";
});

async function loadRecords(applicationName = "") {
  const policyPath = applicationName ? `/api/policies?applicationName=${encodeURIComponent(applicationName)}` : "/api/policies";
  syncDeveloperFields();
  const developer = currentDeveloper();
  const manageablePath = developer
    ? `/api/policies/manageable?developer=${encodeURIComponent(developer)}`
    : "/api/policies/manageable";
  const [recordsResponse, manageableResponse] = await Promise.all([
    fetch(policyPath),
    fetch(manageablePath),
  ]);
  const data = await recordsResponse.json();
  const manageableData = await manageableResponse.json();
  const policies = data.policies || [];
  listedPolicies = policies;
  manageablePolicies = manageableData.policies || [];
  recordCount.textContent = String(policies.length);
  manageableCount.textContent = String(manageablePolicies.length);
  renderManagedPolicies();
  recordList.innerHTML = policies
    .map((policy) => {
      const version = policy.policy_version || "unversioned";
      const name = displayPolicyName(policy);
      return `<article class="record-card">
        <h3>${escapeHtml(name)}</h3>
        <p>Policy ID: ${escapeHtml(policy.policy_id)}</p>
        <p>Developer: ${escapeHtml(policy.developer_name || "unknown")}</p>
        <p>Uploaded: ${escapeHtml(version)}</p>
        <p>Hash: ${escapeHtml(shorten(policy.hash_code))}</p>
        <p>Tx: ${escapeHtml(shorten(policy.tx_hash))}</p>
        <p>Created: ${escapeHtml(policy.created_at)}</p>
        <button
          class="record-action"
          type="button"
          data-use-record
          data-record-id="${escapeHtml(policy.id)}"
        >Load Text for Verify</button>
      </article>`;
    })
    .join("");
}

function renderManagedPolicies() {
  const currentValue = managedPolicySelect.value;
  managedPolicySelect.innerHTML = `<option value="">Select a policy for ${escapeHtml(currentDeveloper())}</option>`;
  manageablePolicies.forEach((policy) => {
    const name = displayPolicyName(policy);
    const option = document.createElement("option");
    option.value = policy.policy_id;
    option.textContent = `${name} (${policy.policy_version || "no upload time"})`;
    managedPolicySelect.append(option);
  });
  if (manageablePolicies.some((policy) => policy.policy_id === currentValue)) {
    managedPolicySelect.value = currentValue;
  }
  syncSelectedPolicy();
}

function syncSelectedPolicy() {
  const selected = manageablePolicies.find((policy) => policy.policy_id === managedPolicySelect.value);
  if (!selected) {
    selectedPolicyBox.textContent = "No policy selected.";
    return;
  }
  const name = displayPolicyName(selected);
  selectedPolicyBox.textContent = [
    `Application Name: ${name}`,
    `Policy ID: ${selected.policy_id}`,
    `Developer: ${selected.developer_name || "unknown"}`,
    `Latest Upload: ${selected.policy_version || "no upload time"}`,
    `Current Hash: ${shorten(selected.hash_code)}`,
  ].join("\n");
}

function displayPolicyName(policy) {
  return policy.policy_name || (policy.metadata && policy.metadata.applicationName) || policy.policy_id;
}

function renderQueryFullText(policy) {
  queryFullText.textContent = [
    `Application Name: ${displayPolicyName(policy)}`,
    `Developer: ${policy.developer_name || "unknown"}`,
    `Uploaded: ${policy.policy_version || "no upload time"}`,
    `Policy ID: ${policy.policy_id}`,
    "",
    policy.raw_file,
  ].join("\n");
}

function currentDeveloper() {
  return developerSelect.value;
}

function syncDeveloperFields() {
  policyForm.developer.value = currentDeveloper();
  updateForm.developer.value = currentDeveloper();
}

function formatError(error) {
  const duplicate = error.details && error.details.duplicate;
  if (!duplicate) {
    return error.message;
  }
  return [
    error.message,
    `Existing application: ${duplicate.applicationName}`,
    `Policy ID: ${duplicate.policyId}`,
    `Developer: ${duplicate.developer}`,
    `Uploaded: ${duplicate.uploadTime}`,
    `Hash: ${shorten(duplicate.hashCode)}`,
  ].join("\n");
}

function renderProcessingResult(result) {
  const report = result.report;
  readinessMetric.textContent = `${report.readinessScore}%`;
  hashValue.textContent = shorten(report.hashCode);
  txValue.textContent = shorten(result.onChain.txHash);
  storageValue.textContent = `Saved row #${result.policy.id}`;
  blockValue.textContent = `Block ${result.onChain.blockNumber}`;
  reportBox.textContent = [
    `Policy ID: ${result.policy.policy_id}`,
    `Application Name: ${result.policy.policy_name}`,
    `Developer: ${result.policy.developer_name}`,
    `Uploaded: ${result.policy.policy_version}`,
    report.summary,
    `Covered: ${report.coveredTopics.join(", ") || "none"}`,
    `Missing: ${report.missingTopics.join(", ") || "none"}`,
    `Recommendation: ${report.recommendation}`,
  ].join("\n");
}

function renderVerification(result) {
  verificationBox.className = `verification ${result.verified ? "pass" : "fail"}`;
  const comparisons = Object.entries(result.comparisons)
    .map(([name, value]) => `${name}: ${value ? "pass" : "fail"}`)
    .join("\n");
  verificationBox.textContent = [
    result.verified ? "Verified trusted policy record." : "Verification failed.",
    result.reason,
    result.stored ? `Application Name: ${displayPolicyName(result.stored)}` : "",
    result.stored ? `Uploaded: ${result.stored.policy_version}` : "",
    comparisons,
    `SQL hash: ${shorten(result.sqlHash)}`,
    `Chain hash: ${shorten(result.chainHash)}`,
  ].filter(Boolean).join("\n");
}

function setBusy(isBusy) {
  systemStatus.textContent = isBusy ? "Processing workflow" : "Local chain ready";
  document.querySelectorAll("button").forEach((button) => {
    button.disabled = isBusy;
  });
}

function shorten(value) {
  if (!value) {
    return "";
  }
  return value.length > 22 ? `${value.slice(0, 12)}...${value.slice(-8)}` : value;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

syncDeveloperFields();
loadRecords();
