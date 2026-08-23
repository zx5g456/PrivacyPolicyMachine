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
const recordsDetail = document.querySelector("#recordsDetail");
const verificationBox = document.querySelector("#verificationBox");
const updateBox = document.querySelector("#updateBox");
const selectedPolicyBox = document.querySelector("#selectedPolicyBox");
const recordList = document.querySelector("#recordList");
const recordCount = document.querySelector("#recordCount");
const manageableCount = document.querySelector("#manageableCount");
const systemStatus = document.querySelector("#systemStatus");
const methodDialog = document.querySelector("#methodDialog");
const closeMethodDialog = document.querySelector("#closeMethodDialog");
const reviewTab = document.querySelector("#reviewTab");
const reviewMethod = document.querySelector("#reviewMethod");
const reviewGuidance = document.querySelector("#reviewGuidance");
const reviewFields = document.querySelector("#reviewFields");
const reviewPolicy = document.querySelector("#reviewPolicy");
const reviewStatus = document.querySelector("#reviewStatus");
const confirmReview = document.querySelector("#confirmReview");
const cancelReview = document.querySelector("#cancelReview");
const viewTabs = document.querySelectorAll("[data-view]");
const viewPages = document.querySelectorAll("[data-page]");
let manageablePolicies = [];
let listedPolicies = [];
let chainRecordsByTx = new Map();
let currentEvidence = {};
let currentAssessment = {};
let pendingReview = null;

const reviewFieldDefinitions = [
  ["data_type_tags", "Data Types", "list"],
  ["data_source_types", "Data Sources", "list"],
  ["collection_context", "Collection Context", "list"],
  ["processing_purpose", "Processing Purpose", "list"],
  ["third_party_sources", "Third-party Sources", "list"],
  ["downstream_stakeholders", "Downstream Stakeholders", "list"],
  ["third_party_purpose", "Third-party Purpose", "list"],
  ["regulatory_framework", "Regulatory Framework", "list"],
  ["sharing_condition", "Sharing Condition", "status"],
  ["consent_required", "Consent Required", "status"],
  ["opt_out_available", "Opt-out Available", "status"],
  ["deletion_available", "Deletion Available", "status"],
  ["request_channel", "Request Channel", "status"],
  ["retention_policy", "Retention Policy", "status"],
  ["encryption_applied", "Encryption Applied", "status"],
  ["anonymisation", "Anonymisation", "status"],
  ["cross_border_transfer", "Cross-border Transfer", "status"],
  ["child_data_involved", "Child Data Involved", "status"],
  ["contact_channel", "Contact Channel", "status"],
  ["risk_flags", "Risk Flags", "list"],
];

const reviewListOptions = {
  data_type_tags: ["location", "voice_recording", "eye_tracking", "device_id", "payment_info", "contact_info"],
  data_source_types: ["user_provided", "device_sensor", "third_party_login", "cookies", "xr_headset_sensor"],
  collection_context: ["during_payment", "account_registration", "service_usage", "customer_support"],
  processing_purpose: ["advertising", "analytics", "payment_processing", "service_provision", "security"],
  third_party_sources: ["google_login", "facebook_login", "payment_processor"],
  downstream_stakeholders: ["cloud_provider", "analytics_provider", "advertising_partner", "payment_processor"],
  third_party_purpose: ["payment_processing", "analytics", "advertising", "service_delivery"],
  regulatory_framework: ["GDPR", "CCPA", "COPPA", "HIPAA"],
  risk_flags: ["unclear_retention", "vague_third_party_sharing", "no_deletion_method", "sensitive_data_involved"],
};

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

viewTabs.forEach((tab) => {
  tab.addEventListener("click", () => showView(tab.dataset.view));
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
  if (!policyForm.rawFile.files.length) {
    reportBox.textContent = "Please upload a policy file.";
    return;
  }
  methodDialog.hidden = false;
});

closeMethodDialog.addEventListener("click", () => { methodDialog.hidden = true; });
methodDialog.addEventListener("click", (event) => {
  if (event.target === methodDialog) {
    methodDialog.hidden = true;
  }
});
document.querySelectorAll("[data-upload-method]").forEach((button) => {
  button.addEventListener("click", () => startUploadWorkflow(button.dataset.uploadMethod));
});
cancelReview.addEventListener("click", clearReview);
confirmReview.addEventListener("click", registerReviewedPolicy);

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
      queryBox.textContent = `Found ${listedPolicies.length} record(s). Showing the latest matching policy.`;
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
      `Upload method: ${uploadMethodLabel(result.policy.upload_method)}`,
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

async function startUploadWorkflow(method) {
  methodDialog.hidden = true;
  const path = {
    fast: "/api/policies",
    ai: "/api/analyze",
    manual: "/api/policies/manual",
  }[method];
  if (!path) {
    return;
  }
  setBusy(true);
  reportBox.textContent = method === "ai" ? "Running local AI analysis..." : "Running keyword analysis...";
  try {
    const result = await postForm(path, new FormData(policyForm));
    if (method === "fast") {
      await completeRegistration(result);
      return;
    }
    openReview(result, method);
  } catch (error) {
    reportBox.textContent = formatError(error);
  } finally {
    setBusy(false);
  }
}

function openReview(result, method) {
  normalizeReviewMetadata(result.metadata);
  pendingReview = {
    method,
    metadata: structuredClone(result.metadata),
    file: policyForm.rawFile.files[0],
    applicationName: policyForm.applicationName.value.trim(),
    developer: policyForm.developer.value,
    policyUrl: policyForm.policyUrl.value.trim(),
    effectiveDate: policyForm.effectiveDate.value,
  };
  reviewMethod.textContent = method === "ai" ? "AI upload · human approval required" : "Manual upload · keyword draft";
  reviewGuidance.textContent = method === "ai"
    ? "The local model produced the draft below. Check every value and correct it before registration."
    : "Keyword rules produced the draft below. Edit any incorrect or incomplete values before registration.";
  reviewPolicy.textContent = pendingReview.file ? "Loading policy text..." : "Policy text unavailable.";
  if (pendingReview.file) {
    pendingReview.file.text().then((text) => { reviewPolicy.textContent = text; });
  }
  reviewFields.innerHTML = reviewFieldDefinitions.map(([key, label, type]) => {
    const value = pendingReview.metadata[key];
    const evidence = reviewEvidenceLines(pendingReview.metadata.metadataEvidence && pendingReview.metadata.metadataEvidence[key]);
    const evidenceControl = `<label class="review-evidence-label">Evidence
      <textarea class="review-evidence" data-review-evidence="${escapeHtml(key)}" placeholder="No evidence. Add one exact quotation per line if available.">${escapeHtml(evidence.join("\n"))}</textarea>
    </label>`;
    if (type === "status") {
      const choices = ["yes", "no", "unclear"];
      if (value && !choices.includes(String(value))) {
        choices.push(String(value));
      }
      return `<section class="review-field-group"><label>${escapeHtml(label)}
          <select data-review-field="${escapeHtml(key)}" data-review-type="status">
            ${choices.map((choice) => `<option value="${escapeHtml(choice)}" ${String(value) === choice ? "selected" : ""}>${escapeHtml(choice)}</option>`).join("")}
          </select>
        </label>${evidenceControl}</section>`;
    }
    return renderReviewListField(key, label, value, pendingReview.metadata.metadataEvidence[key]);
  }).join("");
  reviewStatus.className = "verification";
  reviewStatus.textContent = "Review every field before registration.";
  reviewTab.hidden = false;
  showView("review", { skipLoad: true });
}

async function registerReviewedPolicy() {
  if (!pendingReview) {
    return;
  }
  reviewFields.querySelectorAll("[data-review-field]").forEach((control) => {
    const key = control.dataset.reviewField;
    pendingReview.metadata[key] = control.value;
  });
  pendingReview.metadata.metadataEvidence = pendingReview.metadata.metadataEvidence || {};
  reviewFields.querySelectorAll("[data-review-evidence]").forEach((control) => {
    pendingReview.metadata.metadataEvidence[control.dataset.reviewEvidence] = control.value
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
  });
  reviewFieldDefinitions.filter((definition) => definition[2] === "list").forEach(([key]) => {
    const selectedItems = [...reviewFields.querySelectorAll(`[data-review-list-item="${key}"]:checked`)]
      .map((control) => control.value);
    const itemEvidence = {};
    reviewFields.querySelectorAll(`[data-review-item-evidence="${key}"]`).forEach((control) => {
      const lines = control.value.split("\n").map((line) => line.trim()).filter(Boolean);
      if (selectedItems.includes(control.dataset.reviewItem) && lines.length) {
        itemEvidence[control.dataset.reviewItem] = lines;
      }
    });
    pendingReview.metadata[key] = selectedItems;
    pendingReview.metadata.metadataEvidence[key] = itemEvidence;
  });
  const payload = new FormData();
  payload.append("applicationName", pendingReview.applicationName);
  payload.append("developer", pendingReview.developer);
  payload.append("policyUrl", pendingReview.policyUrl);
  payload.append("effectiveDate", pendingReview.effectiveDate);
  payload.append("uploadMethod", pendingReview.method);
  payload.append("metadataJson", JSON.stringify(pendingReview.metadata));
  payload.append("rawFile", pendingReview.file, pendingReview.file.name);
  setBusy(true);
  try {
    const result = await postForm("/api/policies/reviewed", payload);
    await completeRegistration(result);
    clearReview();
    showView("create", { skipLoad: true });
  } catch (error) {
    reviewStatus.className = "verification fail";
    reviewStatus.textContent = formatError(error);
  } finally {
    setBusy(false);
  }
}

function renderReviewListField(key, label, value, evidence) {
  const selected = Array.isArray(value) ? value.map(String) : [];
  const options = [...new Set([...(reviewListOptions[key] || []), ...selected])];
  const evidenceByItem = evidence && typeof evidence === "object" && !Array.isArray(evidence) ? evidence : {};
  return `<section class="review-field-group review-list-group">
    <h3>${escapeHtml(label)}</h3>
    <div class="review-list-items">
      ${options.map((item) => {
        const lines = reviewEvidenceLines(evidenceByItem[item]);
        return `<section class="review-list-item">
          <label class="review-item-toggle">
            <input type="checkbox" data-review-list-item="${escapeHtml(key)}" value="${escapeHtml(item)}" ${selected.includes(item) ? "checked" : ""}>
            <span>${escapeHtml(item)}</span>
          </label>
          <label class="review-evidence-label">Evidence for ${escapeHtml(item)}
            <textarea class="review-evidence" data-review-item-evidence="${escapeHtml(key)}" data-review-item="${escapeHtml(item)}" placeholder="No evidence for this item.">${escapeHtml(lines.join("\n"))}</textarea>
          </label>
        </section>`;
      }).join("")}
    </div>
  </section>`;
}

function normalizeReviewMetadata(metadata) {
  metadata.metadataEvidence = metadata.metadataEvidence || {};
  reviewFieldDefinitions.forEach(([key, _label, type]) => {
    if (type !== "status") {
      return;
    }
    const evidence = reviewEvidenceLines(metadata.metadataEvidence[key]);
    if ((metadata[key] === "yes" || metadata[key] === "no") && !evidence.length) {
      metadata[key] = "unclear";
    } else if (metadata[key] === "mentioned") {
      metadata[key] = evidence.length ? "yes" : "unclear";
    } else if (!metadata[key]) {
      metadata[key] = "unclear";
    }
  });
}

function reviewEvidenceLines(evidence) {
  if (!evidence) {
    return [];
  }
  if (Array.isArray(evidence)) {
    return evidence.map(String).filter(Boolean);
  }
  if (typeof evidence === "object") {
    return Object.values(evidence).flatMap((value) => reviewEvidenceLines(value));
  }
  return [String(evidence)].filter(Boolean);
}

function clearReview() {
  pendingReview = null;
  reviewFields.innerHTML = "";
  reviewPolicy.textContent = "";
  reviewTab.hidden = true;
  showView("create", { skipLoad: true });
}

async function completeRegistration(result) {
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
    renderRecordDetail(policy);
  }
});

function showView(viewName, options = {}) {
  viewTabs.forEach((tab) => {
    const isActive = tab.dataset.view === viewName;
    tab.classList.toggle("active", isActive);
    tab.setAttribute("aria-selected", String(isActive));
  });
  viewPages.forEach((page) => {
    const isActive = page.dataset.page === viewName;
    page.classList.toggle("active", isActive);
    page.hidden = !isActive;
  });
  if (options.skipLoad) {
    return;
  }
  if (viewName === "records") {
    loadRecords();
  } else if (viewName === "update") {
    loadRecords(queryForm.applicationName.value.trim());
  }
}

async function loadRecords(applicationName = "") {
  const policyPath = applicationName ? `/api/policies?applicationName=${encodeURIComponent(applicationName)}` : "/api/policies";
  syncDeveloperFields();
  const developer = currentDeveloper();
  const manageablePath = developer
    ? `/api/policies/manageable?developer=${encodeURIComponent(developer)}`
    : "/api/policies/manageable";
  const [recordsResponse, manageableResponse, chainResponse] = await Promise.all([
    fetch(policyPath),
    fetch(manageablePath),
    fetch("/api/chain"),
  ]);
  const data = await recordsResponse.json();
  const manageableData = await manageableResponse.json();
  const chainData = await chainResponse.json();
  const policies = data.policies || [];
  const chainRecords = chainData.records || [];
  chainRecordsByTx = new Map(chainRecords.map((record) => [record.txHash, record]));
  listedPolicies = policies;
  manageablePolicies = manageableData.policies || [];
  recordCount.textContent = String(policies.length);
  manageableCount.textContent = String(manageablePolicies.length);
  renderManagedPolicies();
  recordList.innerHTML = policies
    .map((policy) => {
      const version = policy.policy_version || "unversioned";
      const name = displayPolicyName(policy);
      const metadata = displayMetadataForPolicy(policy);
      return `<article class="record-card">
        <h3>${escapeHtml(name)}</h3>
        <p>Policy ID: ${escapeHtml(policy.policy_id)}</p>
        <p>Developer: ${escapeHtml(policy.developer_name || "unknown")}</p>
        <p>Upload method: ${escapeHtml(uploadMethodLabel(policy.upload_method))}</p>
        <p>Uploaded: ${escapeHtml(version)}</p>
        <p>Hash: ${escapeHtml(shorten(policy.hash_code))}</p>
        <p>Tx: ${escapeHtml(shorten(policy.tx_hash))}</p>
        <p>Created: ${escapeHtml(policy.created_at)}</p>
        ${renderMetadataSummaryHtml(metadata)}
        <button
          class="record-action"
          type="button"
          data-use-record
          data-record-id="${escapeHtml(policy.id)}"
        >View Details</button>
      </article>`;
    })
    .join("");
  if (!policies.length) {
    recordsDetail.textContent = "No records available.";
  } else {
    renderRecordDetail(policies[0]);
  }
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
    `Upload method: ${uploadMethodLabel(selected.upload_method)}`,
    `Latest Upload: ${selected.policy_version || "no upload time"}`,
    `Current Hash: ${shorten(selected.hash_code)}`,
  ].join("\n");
}

function displayPolicyName(policy) {
  return policy.policy_name || (policy.metadata && policy.metadata.applicationName) || policy.policy_id;
}

function renderQueryFullText(policy) {
  const onChain = findOnChainRecord(policy);
  const onChainData = displayMetadataForPolicy(policy);
  queryFullText.innerHTML = renderPolicyDetailHtml(policy, onChain, onChainData);
}

function renderRecordDetail(policy) {
  const onChain = findOnChainRecord(policy);
  const onChainData = displayMetadataForPolicy(policy);
  recordsDetail.innerHTML = renderPolicyDetailHtml(policy, onChain, onChainData);
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
  const onChainData = result.onChain && result.onChain.data;
  readinessMetric.textContent = `${report.readinessScore}%`;
  hashValue.textContent = shorten(report.hashCode);
  txValue.textContent = shorten(result.onChain.txHash);
  storageValue.textContent = `Saved row #${result.policy.id}`;
  blockValue.textContent = `Block ${result.onChain.blockNumber}`;
  reportBox.textContent = [
    `Policy ID: ${result.policy.policy_id}`,
    `Application Name: ${result.policy.policy_name}`,
    `Developer: ${result.policy.developer_name}`,
    `Upload method: ${uploadMethodLabel(result.policy.upload_method)}`,
    `Uploaded: ${result.policy.policy_version}`,
    report.summary,
    `Covered: ${report.coveredTopics.join(", ") || "none"}`,
    `Missing: ${report.missingTopics.join(", ") || "none"}`,
    `Recommendation: ${report.recommendation}`,
    "",
    "On-chain metadata:",
    onChainData ? formatOnChainMetadata(onChainData) : "No on-chain metadata returned.",
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
    result.normalization ? `Text comparison: ${result.normalization}` : "",
    typeof result.exactHashesMatch === "boolean" ? `Exact file hash matches stored record: ${result.exactHashesMatch ? "yes" : "no"}` : "",
    `Stored hash: ${shorten(result.sqlHash)}`,
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

function uploadMethodLabel(method) {
  return { fast: "Fast Upload", ai: "AI Upload", manual: "Manual Upload" }[method] || method || "Fast Upload";
}

function findOnChainRecord(policy) {
  return chainRecordsByTx.get(policy.tx_hash) || null;
}

function displayMetadataForPolicy(policy) {
  const fallback = metadataFallback(policy);
  const onChain = findOnChainRecord(policy);
  return mergeMetadata(onChain ? onChain.data : null, fallback);
}

function mergeMetadata(primary, fallback) {
  if (!primary) {
    return fallback;
  }
  const merged = { ...fallback, ...primary };
  Object.keys(fallback).forEach((key) => {
    if (!hasValue(primary[key])) {
      merged[key] = fallback[key];
    }
  });
  return merged;
}

function metadataFallback(policy) {
  const metadata = policy.metadata || {};
  return {
    rawFile: policy.raw_file || "",
    policyVersion: policy.policy_version || metadata.policy_version || metadata.policyVersion || "",
    publisherEntity: metadata.publisher_entity || policy.developer_name || "",
    policyUrl: metadata.policy_url || "",
    serviceName: metadata.service_name || displayPolicyName(policy),
    effectiveDate: metadata.effective_date || "",
    dataTypeTags: valueText(metadata.data_type_tags),
    dataSourceTypes: valueText(metadata.data_source_types),
    collectionContext: valueText(metadata.collection_context),
    processingPurpose: valueText(metadata.processing_purpose),
    permittedUsage: valueText(metadata.permitted_usage),
    thirdPartySources: valueText(metadata.third_party_sources),
    downstreamStakeholders: valueText(metadata.downstream_stakeholders),
    thirdPartyPurpose: valueText(metadata.third_party_purpose),
    sharingCondition: valueText(metadata.sharing_condition),
    consentRequired: valueText(metadata.consent_required),
    optOutAvailable: valueText(metadata.opt_out_available),
    deletionAvailable: valueText(metadata.deletion_available),
    requestChannel: valueText(metadata.request_channel),
    retentionPolicy: valueText(metadata.retention_policy),
    encryptionApplied: valueText(metadata.encryption_applied),
    anonymisation: valueText(metadata.anonymisation),
    regulatoryFramework: valueText(metadata.regulatory_framework),
    crossBorderTransfer: valueText(metadata.cross_border_transfer),
    childDataInvolved: valueText(metadata.child_data_involved),
    changeSummary: valueText(metadata.change_summary),
    contactChannel: valueText(metadata.contact_channel),
    riskFlags: valueText(metadata.risk_flags),
    metadataEvidence: metadata.metadataEvidence || {},
    metadataAssessment: metadata.metadataAssessment || {},
    previousRecordKey: "",
    previousPolicyVersion: "",
    hasPreviousReference: false,
    documentHash: "",
    metadataHash: "",
    registrant: "",
    registeredAt: "",
  };
}

function renderPolicyDetailHtml(policy, onChain, data) {
  const rawFile = policy.raw_file || "";
  const rawPreview = rawFile.length > 900 ? `${rawFile.slice(0, 900)}...` : rawFile;
  currentEvidence = data.metadataEvidence || {};
  currentAssessment = data.metadataAssessment || {};
  return `
    <section class="policy-detail">
      <div class="policy-detail-header">
        <div>
          <h3>${escapeHtml(displayPolicyName(policy))}</h3>
          <p>${escapeHtml(policy.developer_name || "unknown")} · ${escapeHtml(policy.policy_version || "no upload time")} · ${escapeHtml(uploadMethodLabel(policy.upload_method))}</p>
        </div>
        <div class="record-key">${escapeHtml(shorten(onChain ? onChain.recordKey || "" : "")) || "no record key"}</div>
      </div>

      <div class="metadata-grid-detail">
        ${metadataGroups(data).map(([title, rows]) => renderMetadataGroupHtml(title, rows)).join("")}
      </div>

      <section class="raw-preview">
        <div class="raw-preview-heading">
          <h3>Raw Policy Preview</h3>
          <span>${escapeHtml(String(rawFile.length))} characters</span>
        </div>
        <pre>${escapeHtml(rawPreview || "No raw policy text available.")}</pre>
        <details>
          <summary>Full Raw Policy</summary>
          <pre>${escapeHtml(rawFile || "No raw policy text available.")}</pre>
        </details>
      </section>
    </section>
  `;
}

function renderMetadataGroupHtml(title, rows) {
  return `
    <section class="metadata-group">
      <h3>${escapeHtml(title)}</h3>
      <dl>
        ${rows.map(([label, value, evidenceKey]) => `
          <div>
            <dt>${escapeHtml(label)}</dt>
            <dd>
              <span>${escapeHtml(displayValue(value))}</span>
              ${renderAssessmentHtml(evidenceKey, value)}
              ${renderEvidenceHtml(evidenceKey)}
            </dd>
          </div>
        `).join("")}
      </dl>
    </section>
  `;
}

function formatOnChainMetadata(data) {
  return metadataGroups(data)
    .map(([title, rows]) => {
      const body = rows
        .map(([label, value]) => `  ${label}: ${displayValue(value)}`)
        .join("\n");
      return `${title}\n${body}`;
    })
    .join("\n\n");
}

function metadataGroups(data) {
  return [
    ["Identity", [
      ["Publisher", data.publisherEntity, ""],
      ["Service", data.serviceName, ""],
      ["Policy URL", data.policyUrl, ""],
      ["Effective Date", data.effectiveDate, ""],
      ["Policy Version", data.policyVersion, ""],
    ]],
    ["On-chain Audit", [
      ["Document Hash", data.documentHash, ""],
      ["Metadata Hash", data.metadataHash, ""],
      ["Registrant", data.registrant, ""],
      ["Registered At", data.registeredAt, ""],
      ["Previous Record", data.previousRecordKey, ""],
    ]],
    ["Data Collection", [
      ["Data Types", data.dataTypeTags, "data_type_tags"],
      ["Data Sources", data.dataSourceTypes, "data_source_types"],
      ["Collection Context", data.collectionContext, "collection_context"],
      ["Processing Purpose", data.processingPurpose, "processing_purpose"],
      ["Permitted Usage", data.permittedUsage, "processing_purpose"],
    ]],
    ["Data Sharing", [
      ["Third-party Sources", data.thirdPartySources, "third_party_sources"],
      ["Downstream Stakeholders", data.downstreamStakeholders, "downstream_stakeholders"],
      ["Third-party Purpose", data.thirdPartyPurpose, "third_party_purpose"],
      ["Sharing Condition", data.sharingCondition, "sharing_condition"],
    ]],
    ["User Rights", [
      ["Consent Required", data.consentRequired, "consent_required"],
      ["Opt-out Available", data.optOutAvailable, "opt_out_available"],
      ["Deletion Available", data.deletionAvailable, "deletion_available"],
      ["Request Channel", data.requestChannel, "request_channel"],
    ]],
    ["Retention and Security", [
      ["Retention Policy", data.retentionPolicy, "retention_policy"],
      ["Encryption Applied", data.encryptionApplied, "encryption_applied"],
      ["Anonymisation", data.anonymisation, "anonymisation"],
    ]],
    ["Compliance", [
      ["Regulatory Framework", data.regulatoryFramework, "regulatory_framework"],
      ["Cross-border Transfer", data.crossBorderTransfer, "cross_border_transfer"],
      ["Child Data Involved", data.childDataInvolved, "child_data_involved"],
    ]],
    ["Change and Accountability", [
      ["Change Summary", data.changeSummary, ""],
      ["Contact Channel", data.contactChannel, "contact_channel"],
      ["Risk Flags", data.riskFlags, ""],
    ]],
  ];
}

function renderEvidenceHtml(evidenceKey) {
  if (!evidenceKey) {
    return "";
  }
  const evidence = currentEvidence && currentEvidence[evidenceKey];
  const lines = evidenceLines(evidence);
  if (!lines.length) {
    return "";
  }
  return `<ul class="evidence-list">
    ${lines.map((line) => `<li>${escapeHtml(line)}</li>`).join("")}
  </ul>`;
}

function renderAssessmentHtml(assessmentKey, value) {
  if (!assessmentKey) {
    return "";
  }
  const assessment = assessmentForValue(assessmentKey, value);
  if (!assessment) {
    return "";
  }
  const status = assessment.review_status || "auto_extracted";
  const confidence = Number(assessment.confidence);
  const confidenceText = Number.isFinite(confidence) ? confidence.toFixed(2) : "n/a";
  return `<div class="assessment ${status === "needs_review" ? "needs-review" : ""}">
    <span>Confidence ${escapeHtml(confidenceText)}</span>
    <span>${escapeHtml(statusLabel(status))}</span>
  </div>`;
}

function assessmentForValue(assessmentKey, value) {
  const assessment = currentAssessment && currentAssessment[assessmentKey];
  if (!assessment) {
    return null;
  }
  if (assessment.confidence !== undefined) {
    return assessment;
  }
  const values = valueText(value).split(",").map((item) => item.trim()).filter(Boolean);
  return values
    .map((item) => assessment[item])
    .find(Boolean) || null;
}

function statusLabel(status) {
  return status.replaceAll("_", " ");
}

function evidenceLines(evidence) {
  if (Array.isArray(evidence)) {
    return evidence;
  }
  if (!evidence || typeof evidence !== "object") {
    return [];
  }
  return Object.entries(evidence).flatMap(([label, sentences]) => {
    if (!Array.isArray(sentences)) {
      return [];
    }
    return sentences.map((sentence) => `${label}: ${sentence}`);
  });
}

function renderMetadataSummaryHtml(data) {
  const rows = [
    ["Data", data.dataTypeTags],
    ["Purpose", data.processingPurpose],
    ["Sharing", data.downstreamStakeholders || data.thirdPartySources],
    ["Rights", rightsSummary(data)],
    ["Risk", data.riskFlags],
  ];
  return `<dl class="metadata-summary">
    ${rows.map(([label, value]) => `
      <div>
        <dt>${escapeHtml(label)}</dt>
        <dd>${escapeHtml(displayValue(value))}</dd>
      </div>
    `).join("")}
  </dl>`;
}

function rightsSummary(data) {
  return [
    data.consentRequired ? `consent ${data.consentRequired}` : "",
    data.optOutAvailable ? `opt-out ${data.optOutAvailable}` : "",
    data.deletionAvailable ? `deletion ${data.deletionAvailable}` : "",
  ].filter(Boolean).join(", ");
}

function displayValue(value) {
  const text = valueText(value);
  return text || "not mentioned";
}

function hasValue(value) {
  if (typeof value === "boolean") {
    return value;
  }
  return valueText(value).trim().length > 0;
}

function valueText(value) {
  if (Array.isArray(value)) {
    return value.join(", ");
  }
  if (value === true) {
    return "yes";
  }
  if (value === false) {
    return "no";
  }
  return value == null ? "" : String(value);
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
