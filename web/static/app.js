const policyForm = document.querySelector("#policyForm");
const queryForm = document.querySelector("#queryForm");
const verifyForm = document.querySelector("#verifyForm");
const updateForm = document.querySelector("#updateForm");
const sampleButton = document.querySelector("#sampleButton");
const refreshButton = document.querySelector("#refreshButton");
const developerSelect = document.querySelector("#developerSelect");
const managedPolicySelect = document.querySelector("#managedPolicySelect");
const hashValue = document.querySelector("#hashValue");
const txValue = document.querySelector("#txValue");
const storageValue = document.querySelector("#storageValue");
const blockValue = document.querySelector("#blockValue");
const reportBox = document.querySelector("#reportBox");
const queryBox = document.querySelector("#queryBox");
const queryFullText = document.querySelector("#queryFullText");
const queryPolicyPicker = document.querySelector("#queryPolicyPicker");
const queryPolicySelect = document.querySelector("#queryPolicySelect");
const recordsDetail = document.querySelector("#recordsDetail");
const verificationBox = document.querySelector("#verificationBox");
const updateBox = document.querySelector("#updateBox");
const selectedPolicyBox = document.querySelector("#selectedPolicyBox");
const recordList = document.querySelector("#recordList");
const recordCount = document.querySelector("#recordCount");
const manageableCount = document.querySelector("#manageableCount");
const systemStatus = document.querySelector("#systemStatus");
const reviewTab = document.querySelector("#reviewTab");
const reviewMethod = document.querySelector("#reviewMethod");
const reviewGuidance = document.querySelector("#reviewGuidance");
const reviewFields = document.querySelector("#reviewFields");
const reviewPolicy = document.querySelector("#reviewPolicy");
const reviewSourceStatus = document.querySelector("#reviewSourceStatus");
const reviewStatus = document.querySelector("#reviewStatus");
const confirmReview = document.querySelector("#confirmReview");
const cancelReview = document.querySelector("#cancelReview");
const viewTabs = document.querySelectorAll("[data-view]");
const viewPages = document.querySelectorAll("[data-page]");
let manageablePolicies = [];
let listedPolicies = [];
let queryPolicies = [];
let chainRecordsByTx = new Map();
let chainLookupError = "";
let workflowBusy = false;
let currentEvidence = {};
let currentDetails = {};
let currentAssessment = {};
let pendingReview = null;

const reviewFieldDefinitions = [
  ["dataTypeTags", "Data Types", "list"],
  ["dataSourceTypes", "Data Sources", "list"],
  ["collectionContext", "Collection Context", "list"],
  ["processingPurpose", "Processing Purpose", "list"],
  ["permittedUsage", "Permitted Usage", "list"],
  ["thirdPartySources", "Third-party Sources", "list"],
  ["downstreamStakeholders", "Downstream Stakeholders", "list"],
  ["thirdPartyPurpose", "Third-party Purpose", "list"],
  ["regulatoryFramework", "Regulatory Framework", "list"],
  ["sharingCondition", "Sharing Condition", "status"],
  ["consentRequired", "Consent Required", "status"],
  ["optOutAvailable", "Opt-out Available", "status"],
  ["deletionAvailable", "Deletion Available", "status"],
  ["requestChannel", "Request Channel", "status"],
  ["retentionPolicy", "Retention Policy", "status"],
  ["encryptionApplied", "Encryption Applied", "status"],
  ["anonymisation", "Anonymisation", "status"],
  ["crossBorderTransfer", "Cross-border Transfer", "status"],
  ["childDataInvolved", "Child Data Involved", "status"],
  ["contactChannel", "Contact Channel", "status"],
  ["riskFlags", "Risk Flags", "list"],
];

const reviewFieldHelp = {
  dataTypeTags: "Categories of personal information the policy says it collects or uses, such as location or contact information.",
  dataSourceTypes: "Where that information comes from, such as the user, a device sensor, or another service.",
  collectionContext: "When or during which activity the information is collected.",
  processingPurpose: "Why the organisation processes the information.",
  permittedUsage: "Uses of the information that the policy explicitly allows.",
  thirdPartySources: "Outside services from which the organisation receives information.",
  downstreamStakeholders: "Outside organisations that may receive or process the information.",
  thirdPartyPurpose: "Why information is shared with or processed by those outside organisations.",
  regulatoryFramework: "Privacy laws or regulatory frameworks named in the policy.",
  sharingCondition: "Whether the policy states conditions or limits for sharing information.",
  consentRequired: "Whether the policy says a user must consent before the relevant processing.",
  optOutAvailable: "Whether users can refuse or stop a type of processing or sharing.",
  deletionAvailable: "Whether users can request deletion of their information.",
  requestChannel: "Whether the policy gives users a way to make privacy requests.",
  retentionPolicy: "Whether the policy explains how long information is kept or how retention is decided.",
  encryptionApplied: "Whether the policy says encryption protects information.",
  anonymisation: "Whether the policy describes removing or reducing identifying information.",
  crossBorderTransfer: "Whether the policy discusses transferring information between countries.",
  childDataInvolved: "Whether the policy discusses collecting or handling children's information.",
  contactChannel: "Whether the policy provides a privacy contact method.",
  riskFlags: "Potential concerns inferred from missing, vague, or sensitive policy statements. Check these against the source.",
};

const reviewListOptions = {
  dataTypeTags: ["location", "voice_recording", "eye_tracking", "device_id", "payment_info", "contact_info"],
  dataSourceTypes: ["user_provided", "device_sensor", "third_party_login", "cookies", "xr_headset_sensor"],
  collectionContext: ["during_payment", "account_registration", "service_usage", "customer_support"],
  processingPurpose: ["advertising", "analytics", "payment_processing", "service_provision", "security"],
  permittedUsage: ["service_operation", "personalization", "marketing", "product_improvement"],
  thirdPartySources: ["google_login", "facebook_login", "payment_processor"],
  downstreamStakeholders: ["cloud_provider", "analytics_provider", "advertising_partner", "payment_processor", "email_provider"],
  thirdPartyPurpose: ["payment_processing", "analytics", "advertising", "service_delivery", "authentication", "email_delivery"],
  regulatoryFramework: ["GDPR", "CCPA", "COPPA", "HIPAA"],
  riskFlags: ["unclear_retention", "vague_third_party_sharing", "no_deletion_method", "sensitive_data_involved", "review_recommended"],
};

const samplePolicy = `PRIVACY POLICY:
We collect personal information including name and email when users create an account.
We share limited data with third party vendors that provide hosting and analytics.
We retain records only for the storage period required to provide the service.
Users may access, correct, delete, or opt out of certain processing activities.
We use security safeguards including encryption and access controls.`;

const today = new Date();
policyForm.effectiveDate.value = [
  today.getFullYear(),
  String(today.getMonth() + 1).padStart(2, "0"),
  String(today.getDate()).padStart(2, "0"),
].join("-");

policyForm.rawFile.addEventListener("change", () => {
  const file = policyForm.rawFile.files[0];
  if (file && !policyForm.applicationName.value.trim()) {
    const extensionIndex = file.name.lastIndexOf(".");
    policyForm.applicationName.value = extensionIndex > 0
      ? file.name.slice(0, extensionIndex)
      : file.name;
  }
});

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
  await analyzeForReview(new FormData(policyForm), {
    workflow: "create",
    file: policyForm.rawFile.files[0],
    applicationName: policyForm.applicationName.value.trim(),
    developer: policyForm.developer.value,
    policyUrl: policyForm.policyUrl.value.trim(),
    effectiveDate: policyForm.effectiveDate.value,
    statusBox: reportBox,
  });
});

cancelReview.addEventListener("click", () => clearReview());
confirmReview.addEventListener("click", registerReviewedPolicy);
reviewFields.addEventListener("click", (event) => {
  const button = event.target.closest("[data-evidence-line]");
  if (!button) return;
  const editor = button.closest(".review-evidence-editor").querySelector("textarea");
  const quote = editor.value.split("\n")[Number(button.dataset.evidenceLine)]?.trim();
  locateEvidence(reviewPolicy, quote, reviewSourceStatus);
});
reviewFields.addEventListener("input", (event) => {
  if (!event.target.matches(".review-evidence-editor textarea")) return;
  const editor = event.target.closest(".review-evidence-editor");
  editor.querySelector(".review-quote-links").innerHTML = renderEvidenceLinks(event.target.value);
});
reviewFields.addEventListener("change", (event) => {
  const card = event.target.closest(".review-field-group");
  if (!card) return;
  const summary = card.querySelector(".review-field-summary");
  if (event.target.matches("[data-review-field]")) summary.textContent = event.target.value;
  if (event.target.matches("[data-review-list-item]")) {
    summary.textContent = [...card.querySelectorAll("[data-review-list-item]:checked")]
      .map((item) => item.value).join(", ") || "None selected";
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
    queryPolicies = [...listedPolicies];
    const policyGroups = groupPolicyVersions(queryPolicies);
    queryPolicyPicker.hidden = policyGroups.length < 2;
    queryPolicySelect.innerHTML = policyGroups.map(([policy]) =>
      `<option value="${escapeHtml(policy.id)}">${escapeHtml(displayPolicyName(policy))} · ${escapeHtml(policy.policyId)}</option>`
    ).join("");
    queryBox.className = "verification pass";
    if (queryPolicies.length) {
      renderQueryFullText(policyGroups[0][0]);
      verifyForm.applicationName.value = displayPolicyName(policyGroups[0][0]);
      queryBox.textContent = `Found ${policyGroups.length} matching ${policyGroups.length === 1 ? "policy" : "policies"}. Showing the latest version. Open Previous versions to view history.`;
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

queryPolicySelect.addEventListener("change", () => {
  const policy = queryPolicies.find((item) => String(item.id) === queryPolicySelect.value);
  if (policy) {
    renderQueryFullText(policy);
    verifyForm.applicationName.value = displayPolicyName(policy);
  }
});

queryFullText.addEventListener("click", (event) => {
  if (jumpToSavedEvidence(event, queryFullText)) return;
  const button = event.target.closest("[data-view-version]");
  const policy = button && queryPolicies.find((item) => String(item.id) === button.dataset.recordId);
  if (policy) renderQueryFullText(policy);
});

recordsDetail.addEventListener("click", (event) => {
  if (jumpToSavedEvidence(event, recordsDetail)) return;
  const button = event.target.closest("[data-view-version]");
  const policy = button && listedPolicies.find((item) => String(item.id) === button.dataset.recordId);
  if (policy) selectRecordPolicy(policy);
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
  const selected = manageablePolicies.find((policy) => policy.policyId === updateForm.policyId.value);
  if (!selected) {
    updateBox.className = "verification fail";
    updateBox.textContent = "The selected policy is no longer available. Refresh and try again.";
    return;
  }
  const payload = new FormData(updateForm);
  const metadata = selected.metadata || {};
  payload.append("applicationName", displayPolicyName(selected));
  payload.append("policyUrl", metadata.policyUrl || "");
  payload.append("effectiveDate", metadata.effectiveDate || "");
  await analyzeForReview(payload, {
    workflow: "update",
    policyId: selected.policyId,
    changeSummary: updateForm.changeSummary.value.trim(),
    file: updateForm.rawFile.files[0],
    applicationName: displayPolicyName(selected),
    developer: updateForm.developer.value,
    policyUrl: metadata.policyUrl || "",
    effectiveDate: metadata.effectiveDate || "",
    statusBox: updateBox,
  });
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

async function analyzeForReview(payload, context) {
  setBusy(true);
  context.statusBox.className = context.workflow === "update" ? "verification" : context.statusBox.className;
  context.statusBox.textContent = "Running AI analysis...";
  try {
    const result = await postForm("/api/analyze", payload);
    openReview(result, context);
  } catch (error) {
    if (context.workflow === "update") {
      context.statusBox.className = "verification fail";
    }
    context.statusBox.textContent = formatError(error);
  } finally {
    setBusy(false);
  }
}

function openReview(result, context) {
  normalizeReviewMetadata(result.metadata);
  pendingReview = {
    workflow: context.workflow,
    policyId: context.policyId || "",
    changeSummary: context.changeSummary || "",
    metadata: structuredClone(result.metadata),
    file: context.file,
    applicationName: context.applicationName,
    developer: context.developer,
    policyUrl: context.policyUrl,
    effectiveDate: context.effectiveDate,
  };
  reviewMethod.textContent = context.workflow === "update"
    ? "AI update · human approval required"
    : "AI upload · human approval required";
  reviewGuidance.textContent = "The AI model produced the draft below. Check every value and correct it before registration.";
  reviewPolicy.textContent = pendingReview.file ? "Loading policy text..." : "Policy text unavailable.";
  reviewSourceStatus.textContent = "Select an evidence quote to locate it.";
  if (pendingReview.file) {
    pendingReview.file.text().then((text) => {
      if (pendingReview?.file === context.file) reviewPolicy.textContent = text;
    }).catch(() => {
      reviewPolicy.textContent = "Policy text could not be loaded.";
    });
  }
  reviewFields.innerHTML = reviewFieldDefinitions.map(([key, label, type]) => {
    const value = pendingReview.metadata[key];
    const evidence = reviewEvidenceLines(pendingReview.metadata.metadataEvidence && pendingReview.metadata.metadataEvidence[key]);
    const details = pendingReview.metadata.metadataDetails && pendingReview.metadata.metadataDetails[key] || "";
    const detailsControl = `<label class="review-evidence-label">Details
      <textarea class="review-evidence" data-review-details="${escapeHtml(key)}" placeholder="Add a concise, policy-grounded explanation.">${escapeHtml(details)}</textarea>
    </label>`;
    const evidenceControl = renderReviewEvidenceEditor(`data-review-evidence="${escapeHtml(key)}"`, evidence);
    const header = renderReviewFieldHeader(key, label, type === "list" ? value : value || "unclear", evidence.length);
    if (type === "status") {
      const choices = ["yes", "no", "unclear"];
      if (value && !choices.includes(String(value))) {
        choices.push(String(value));
      }
      return `<details class="review-field-group"><summary>${header}</summary><div class="review-field-body"><label class="review-value-label">Review value
          <select data-review-field="${escapeHtml(key)}" data-review-type="status">
            ${choices.map((choice) => `<option value="${escapeHtml(choice)}" ${String(value) === choice ? "selected" : ""}>${escapeHtml(choice)}</option>`).join("")}
          </select>
        </label>${detailsControl}${evidenceControl}</div></details>`;
    }
    return renderReviewListField(key, label, value, pendingReview.metadata.metadataEvidence[key], details);
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
  pendingReview.metadata.metadataDetails = pendingReview.metadata.metadataDetails || {};
  reviewFields.querySelectorAll("[data-review-details]").forEach((control) => {
    pendingReview.metadata.metadataDetails[control.dataset.reviewDetails] = control.value.trim();
  });
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
  payload.append("metadataJson", JSON.stringify(pendingReview.metadata));
  payload.append("rawFile", pendingReview.file, pendingReview.file.name);
  if (pendingReview.workflow === "update") {
    payload.append("policyId", pendingReview.policyId);
    payload.append("changeSummary", pendingReview.changeSummary);
  }
  const workflow = pendingReview.workflow;
  const reviewedFile = pendingReview.file;
  const path = workflow === "update" ? "/api/policies/update" : "/api/policies/reviewed";
  setBusy(true);
  try {
    const result = await postForm(path, payload);
    await completeRegistration(result, reviewedFile);
    if (workflow === "update") {
      updateBox.className = "verification pass";
      updateBox.textContent = [
        result.message,
        `Policy ID: ${result.policy.policyId}`,
        `Application Name: ${result.policy.policyName}`,
        `Uploaded: ${result.policy.policyVersion}`,
        `Hash: ${shorten(result.policy.hashCode)}`,
      ].join("\n");
    }
    clearReview(workflow);
  } catch (error) {
    reviewStatus.className = "verification fail";
    reviewStatus.textContent = formatError(error);
  } finally {
    setBusy(false);
  }
}

function renderReviewListField(key, label, value, evidence, details) {
  const selected = Array.isArray(value) ? value.map(String) : [];
  const options = [...new Set([...(reviewListOptions[key] || []), ...selected])];
  const evidenceByItem = evidence && typeof evidence === "object" && !Array.isArray(evidence) ? evidence : {};
  return `<details class="review-field-group review-list-group">
    <summary>${renderReviewFieldHeader(key, label, selected, reviewEvidenceLines(evidence).length)}</summary>
    <div class="review-field-body"><div class="review-list-items">
      ${options.map((item) => {
        const lines = reviewEvidenceLines(evidenceByItem[item]);
        return `<section class="review-list-item">
          <label class="review-item-toggle">
            <input type="checkbox" data-review-list-item="${escapeHtml(key)}" value="${escapeHtml(item)}" ${selected.includes(item) ? "checked" : ""}>
            <span>${escapeHtml(item.replaceAll("_", " "))}</span>
          </label>
          ${renderReviewEvidenceEditor(`data-review-item-evidence="${escapeHtml(key)}" data-review-item="${escapeHtml(item)}"`, lines, `Evidence for ${item}`)}
        </section>`;
      }).join("")}
    </div>
    <label class="review-evidence-label">Details
      <textarea class="review-evidence" data-review-details="${escapeHtml(key)}" placeholder="Add a concise, policy-grounded explanation.">${escapeHtml(details || "")}</textarea>
    </label>
    </div></details>`;
}

function renderReviewFieldHeader(key, label, value, evidenceCount) {
  const summary = Array.isArray(value) ? (value.length ? value.join(", ") : "None selected") : String(value);
  return `<span class="review-field-heading"><span class="review-field-title">${escapeHtml(label)}</span>
    <span class="review-field-summary">${escapeHtml(summary)}</span>
    <span class="review-field-count">${evidenceCount} ${evidenceCount === 1 ? "quote" : "quotes"}</span></span>
    <span class="review-field-help">${escapeHtml(reviewFieldHelp[key])}</span>`;
}

function renderReviewEvidenceEditor(attributes, lines, label = "Evidence") {
  const text = lines.join("\n");
  return `<div class="review-evidence-editor"><label class="review-evidence-label">${escapeHtml(label)}
    <textarea class="review-evidence" ${attributes} placeholder="Add one exact quotation per line if available.">${escapeHtml(text)}</textarea>
  </label><div class="review-quote-links">${renderEvidenceLinks(text)}</div></div>`;
}

function renderEvidenceLinks(text) {
  return text.split("\n").map((line, index) => line.trim()
    ? `<button type="button" class="evidence-jump" data-evidence-line="${index}" title="Find this quote in the policy">Find quote ${index + 1} in policy ↗</button>`
    : "").join("");
}

function locateEvidence(pre, quote, status) {
  const source = pre.textContent;
  if (!quote || !source || source === "Loading policy text...") {
    status.textContent = "Policy text or quote is unavailable.";
    return;
  }
  const start = source.indexOf(quote);
  if (start < 0) {
    status.textContent = "This quote was not found exactly in the policy text. Check its wording.";
    return;
  }
  pre.innerHTML = `${escapeHtml(source.slice(0, start))}<mark class="source-highlight">${escapeHtml(quote)}</mark>${escapeHtml(source.slice(start + quote.length))}`;
  pre.querySelector("mark").scrollIntoView({ block: "center", behavior: "smooth" });
  status.textContent = `Quote found at character ${start + 1}.`;
}

function normalizeReviewMetadata(metadata) {
  metadata.metadataEvidence = metadata.metadataEvidence || {};
  metadata.metadataDetails = metadata.metadataDetails || {};
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

function clearReview(destination) {
  const workflow = destination || (pendingReview && pendingReview.workflow) || "create";
  pendingReview = null;
  reviewFields.innerHTML = "";
  reviewPolicy.textContent = "";
  reviewTab.hidden = true;
  showView(workflow === "update" ? "update" : "create", { skipLoad: true });
}

async function completeRegistration(result, reviewedFile) {
  renderProcessingResult(result);
  if (reviewedFile) {
    const transfer = new DataTransfer();
    transfer.items.add(reviewedFile);
    verifyForm.rawFile.files = transfer.files;
  }
  verifyForm.applicationName.value = result.policy.policyName;
  await loadRecords();
  managedPolicySelect.value = result.policy.policyId;
  syncSelectedPolicy();
}

recordList.addEventListener("click", (event) => {
  const button = event.target.closest("[data-use-record]");
  if (!button) {
    return;
  }
  const policy = listedPolicies.find((item) => String(item.id) === button.dataset.recordId);
  if (policy) {
    selectRecordPolicy(policy);
  }
});

function selectRecordPolicy(policy) {
  verifyForm.rawText.value = policy.rawFile;
  verifyForm.rawFile.value = "";
  verifyForm.applicationName.value = displayPolicyName(policy);
  renderRecordDetail(policy);
}

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
  const [recordsResponse, manageableResponse] = await Promise.all([
    fetch(policyPath),
    fetch(manageablePath),
    loadChainRecords(),
  ]);
  const data = await recordsResponse.json();
  const manageableData = await manageableResponse.json();
  if (!recordsResponse.ok) throw new Error(data.error || "Could not load policies");
  if (!manageableResponse.ok) throw new Error(manageableData.error || "Could not load managed policies");
  const policies = data.policies || [];
  listedPolicies = policies;
  manageablePolicies = manageableData.policies || [];
  const latestPolicies = groupPolicyVersions(policies).map(([latest]) => latest);
  recordCount.textContent = String(latestPolicies.length);
  manageableCount.textContent = String(manageablePolicies.length);
  renderManagedPolicies();
  recordList.innerHTML = latestPolicies
    .map((policy) => {
      const version = policy.policyVersion || "unversioned";
      const name = displayPolicyName(policy);
      const metadata = displayMetadataForPolicy(policy);
      const onChain = findOnChainRecord(policy);
      const complianceStatus = !onChain ? "unavailable" : onChain.compliance
        ? onChain.compliance.status
        : "pending";
      return `<article class="record-card">
        <h3>${escapeHtml(name)}</h3>
        <span class="version-label">Latest version</span>
        <p>Policy ID: ${escapeHtml(policy.policyId)}</p>
        <p>Developer: ${escapeHtml(policy.developerName || "unknown")}</p>
        <p>Upload method: ${escapeHtml(uploadMethodLabel(policy.uploadMethod))}</p>
        <p>Uploaded: ${escapeHtml(version)}</p>
        <p>Hash: ${escapeHtml(shorten(policy.hashCode))}</p>
        <p>Tx: ${escapeHtml(shorten(policy.txHash))}</p>
        <p>Contract Address: ${escapeHtml(policy.contractAddress || (onChain && onChain.contractAddress) || "Not recorded")}</p>
        <p>Chain: ${escapeHtml(chainRecordStatus(onChain))}</p>
        <p>Compliance: <span class="compliance-status ${escapeHtml(complianceStatus)}">${escapeHtml(complianceStatusLabel(complianceStatus))}</span></p>
        <p>Created: ${escapeHtml(policy.createdAt)}</p>
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
    renderRecordDetail(latestPolicies[0]);
  }
}

async function loadChainRecords() {
  try {
    const response = await fetch("/api/chain");
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Could not query the current chain");
    chainRecordsByTx = new Map((payload.records || []).map((record) => [record.txHash.toLowerCase(), record]));
    chainLookupError = "";
  } catch (error) {
    chainRecordsByTx = new Map();
    chainLookupError = error.message || "Could not query the current chain";
  }
  updateSystemStatus();
}

function groupPolicyVersions(policies) {
  // The API returns newest uploads first (createdAt, then id descending).
  const groups = new Map();
  policies.forEach((policy) => {
    const key = policy.policyId || `record:${policy.id}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(policy);
  });
  return [...groups.values()];
}

function policyVersions(policy, policies) {
  return policies.filter((item) => policy.policyId
    ? item.policyId === policy.policyId
    : item.id === policy.id);
}

function renderManagedPolicies() {
  const currentValue = managedPolicySelect.value;
  managedPolicySelect.innerHTML = `<option value="">Select a policy for ${escapeHtml(currentDeveloper())}</option>`;
  manageablePolicies.forEach((policy) => {
    const name = displayPolicyName(policy);
    const option = document.createElement("option");
    option.value = policy.policyId;
    option.textContent = `${name} (${policy.policyVersion || "no upload time"})`;
    managedPolicySelect.append(option);
  });
  if (manageablePolicies.some((policy) => policy.policyId === currentValue)) {
    managedPolicySelect.value = currentValue;
  }
  syncSelectedPolicy();
}

function syncSelectedPolicy() {
  const selected = manageablePolicies.find((policy) => policy.policyId === managedPolicySelect.value);
  if (!selected) {
    selectedPolicyBox.textContent = "No policy selected.";
    return;
  }
  const name = displayPolicyName(selected);
  selectedPolicyBox.textContent = [
    `Application Name: ${name}`,
    `Policy ID: ${selected.policyId}`,
    `Developer: ${selected.developerName || "unknown"}`,
    `Upload method: ${uploadMethodLabel(selected.uploadMethod)}`,
    `Latest Upload: ${selected.policyVersion || "no upload time"}`,
    `Current Hash: ${shorten(selected.hashCode)}`,
  ].join("\n");
}

function displayPolicyName(policy) {
  return policy.policyName || (policy.metadata && policy.metadata.applicationName) || policy.policyId;
}

function renderQueryFullText(policy) {
  const onChain = findOnChainRecord(policy);
  const onChainData = displayMetadataForPolicy(policy);
  queryFullText.innerHTML = renderPolicyDetailHtml(policy, onChain, onChainData, policyVersions(policy, queryPolicies));
  void hydrateCompliancePanel(queryFullText, onChain);
}

function renderRecordDetail(policy) {
  const onChain = findOnChainRecord(policy);
  const onChainData = displayMetadataForPolicy(policy);
  recordsDetail.innerHTML = renderPolicyDetailHtml(policy, onChain, onChainData, policyVersions(policy, listedPolicies));
  void hydrateCompliancePanel(recordsDetail, onChain);
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
  hashValue.textContent = shorten(report.hashCode);
  txValue.textContent = shorten(result.onChain.txHash);
  storageValue.textContent = `Saved row #${result.policy.id}`;
  blockValue.textContent = `Block ${result.onChain.blockNumber}`;
  reportBox.textContent = [
    `Policy ID: ${result.policy.policyId}`,
    `Application Name: ${result.policy.policyName}`,
    `Developer: ${result.policy.developerName}`,
    `Upload method: ${uploadMethodLabel(result.policy.uploadMethod)}`,
    `Uploaded: ${result.policy.policyVersion}`,
    `On-chain chunks: ${onChainData ? onChainData.documentChunkCount + onChainData.metadataChunkCount : 0}`,
    `Chain transactions: ${(result.onChain.transactions || []).length}`,
    report.summary,
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
    result.stored ? `Uploaded: ${result.stored.policyVersion}` : "",
    comparisons,
    result.normalization ? `Text comparison: ${result.normalization}` : "",
    typeof result.exactHashesMatch === "boolean" ? `Exact file hash matches stored record: ${result.exactHashesMatch ? "yes" : "no"}` : "",
    `Stored hash: ${shorten(result.sqlHash)}`,
  ].filter(Boolean).join("\n");
}

function setBusy(isBusy) {
  workflowBusy = isBusy;
  updateSystemStatus();
  document.querySelectorAll("button").forEach((button) => {
    button.disabled = isBusy;
  });
}

function updateSystemStatus() {
  systemStatus.textContent = workflowBusy
    ? "Processing workflow"
    : chainLookupError ? "Chain unavailable" : "Current chain connected";
}

function shorten(value) {
  if (!value) {
    return "";
  }
  return value.length > 22 ? `${value.slice(0, 12)}...${value.slice(-8)}` : value;
}

function uploadMethodLabel(method) {
  return method === "ai" ? "AI Upload" : "Legacy Upload";
}

function findOnChainRecord(policy) {
  const record = chainRecordsByTx.get((policy.txHash || "").toLowerCase());
  if (!record) return null;
  const matchingReceipt = ["contractAddress", "recordKey", "blockHash"].every((key) =>
    !policy[key] || String(policy[key]).toLowerCase() === String(record[key] || "").toLowerCase()
  );
  const matchingChain = policy.chainId == null || String(policy.chainId) === String(record.chainId);
  return matchingReceipt && matchingChain ? record : null;
}

function chainRecordStatus(onChain) {
  if (onChain) return "Found on current chain";
  return chainLookupError ? "Chain query unavailable" : "Not found on current chain";
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
    rawFile: policy.rawFile || "",
    policyVersion: policy.policyVersion || metadata.policyVersion || "",
    publisherEntity: metadata.publisherEntity || policy.developerName || "",
    policyUrl: metadata.policyUrl || "",
    serviceName: metadata.serviceName || displayPolicyName(policy),
    effectiveDate: metadata.effectiveDate || "",
    dataTypeTags: valueText(metadata.dataTypeTags),
    dataSourceTypes: valueText(metadata.dataSourceTypes),
    collectionContext: valueText(metadata.collectionContext),
    processingPurpose: valueText(metadata.processingPurpose),
    permittedUsage: valueText(metadata.permittedUsage),
    thirdPartySources: valueText(metadata.thirdPartySources),
    downstreamStakeholders: valueText(metadata.downstreamStakeholders),
    thirdPartyPurpose: valueText(metadata.thirdPartyPurpose),
    sharingCondition: valueText(metadata.sharingCondition),
    consentRequired: valueText(metadata.consentRequired),
    optOutAvailable: valueText(metadata.optOutAvailable),
    deletionAvailable: valueText(metadata.deletionAvailable),
    requestChannel: valueText(metadata.requestChannel),
    retentionPolicy: valueText(metadata.retentionPolicy),
    encryptionApplied: valueText(metadata.encryptionApplied),
    anonymisation: valueText(metadata.anonymisation),
    regulatoryFramework: valueText(metadata.regulatoryFramework),
    crossBorderTransfer: valueText(metadata.crossBorderTransfer),
    childDataInvolved: valueText(metadata.childDataInvolved),
    changeSummary: valueText(metadata.changeSummary),
    contactChannel: valueText(metadata.contactChannel),
    riskFlags: valueText(metadata.riskFlags),
    metadataEvidence: metadata.metadataEvidence || {},
    metadataDetails: metadata.metadataDetails || {},
    metadataAssessment: metadata.metadataAssessment || {},
    previousRecordKey: "",
    previousPolicyVersion: "",
    hasPreviousReference: false,
    documentHash: policy.hashCode || "",
    metadataHash: policy.metadataHash || "",
    documentChunkCommitment: policy.documentChunkCommitment || "",
    metadataChunkCommitment: policy.metadataChunkCommitment || "",
    documentSize: policy.documentSize || 0,
    metadataSize: policy.metadataSize || 0,
    documentChunkCount: policy.documentChunkCount || 0,
    metadataChunkCount: policy.metadataChunkCount || 0,
    registrant: "",
    registeredAt: "",
  };
}

function renderPolicyDetailHtml(policy, onChain, data, versions = [policy]) {
  const rawFile = policy.rawFile || "";
  const rawPreview = rawFile.length > 900 ? `${rawFile.slice(0, 900)}...` : rawFile;
  currentEvidence = data.metadataEvidence || {};
  currentDetails = data.metadataDetails || {};
  currentAssessment = data.metadataAssessment || {};
  return `
    <section class="policy-detail">
      <div class="policy-detail-header">
        <div>
          <h3>${escapeHtml(displayPolicyName(policy))}</h3>
          <p>${escapeHtml(policy.developerName || "unknown")} · ${escapeHtml(policy.policyVersion || "no upload time")} · ${escapeHtml(uploadMethodLabel(policy.uploadMethod))}</p>
        </div>
        <div class="record-key">${escapeHtml(shorten(policy.recordKey || (onChain && onChain.recordKey) || "")) || "no record key"}</div>
      </div>

      ${renderVersionNavigationHtml(policy, versions)}
      ${renderRegistrationReceiptHtml(policy, onChain)}

      <div class="metadata-grid-detail">
        ${metadataGroups(data, onChain ? "On-chain Audit" : "Saved Audit Data").map(([title, rows]) => renderMetadataGroupHtml(title, rows)).join("")}
      </div>

      ${renderCompliancePanelHtml(onChain)}

      <section class="raw-preview">
        <div class="raw-preview-heading">
          <h3>Raw Policy Preview</h3>
          <span>${escapeHtml(String(rawFile.length))} characters</span>
        </div>
        <p class="source-navigation-status" role="status" aria-live="polite">Select an evidence quote above to find it in the full policy.</p>
        <pre>${escapeHtml(rawPreview || "No raw policy text available.")}</pre>
        <details>
          <summary>Full Raw Policy</summary>
          <pre class="saved-policy-text">${escapeHtml(rawFile || "No raw policy text available.")}</pre>
        </details>
      </section>
    </section>
  `;
}

function renderVersionNavigationHtml(policy, versions) {
  const latest = versions[0] || policy;
  const isLatest = latest.id === policy.id;
  const index = versions.findIndex((version) => version.id === policy.id);
  const previous = versions.slice(1);
  return `<div class="policy-versions">
    <div class="version-heading">
      <span class="version-label">${isLatest ? "Latest version" : "Previous version"} · Version ${versions.length - index} of ${versions.length}</span>
      ${isLatest ? "" : `<button type="button" class="version-action" data-view-version data-record-id="${escapeHtml(latest.id)}">Latest version</button>`}
    </div>
    ${previous.length ? `<details class="policy-history" ${isLatest ? "" : "open"}>
      <summary>Previous versions (${previous.length})</summary>
      <div class="version-list">
        ${previous.map((version, previousIndex) => `<button type="button" class="version-action" data-view-version data-record-id="${escapeHtml(version.id)}" ${version.id === policy.id ? 'aria-current="true"' : ""}>
          Version ${versions.length - previousIndex - 1} · ${escapeHtml(version.policyVersion || version.createdAt || "Upload time unavailable")}
        </button>`).join("")}
      </div>
    </details>` : ""}
  </div>`;
}

function renderRegistrationReceiptHtml(policy, onChain) {
  const receipt = (key) => policy[key] == null || policy[key] === ""
    ? onChain && onChain[key]
    : policy[key];
  const rows = [
    ["Policy ID", policy.policyId],
    ["Contract Address", receipt("contractAddress")],
    ["Transaction Hash", receipt("txHash")],
    ["Record Key", receipt("recordKey")],
    ["Chain ID", receipt("chainId")],
    ["Block Number", receipt("blockNumber")],
    ["Block Hash", receipt("blockHash")],
  ];
  return `<section class="registration-receipt">
    <h3>Saved Registration Receipt</h3>
    <p class="chain-record-status">${escapeHtml(chainRecordStatus(onChain))}</p>
    ${onChain ? "" : `<p>${chainLookupError
      ? "The current chain could not be queried. The saved receipt and policy remain available; their current on-chain status could not be checked."
      : "This saved registration is not present on the current chain. A local chain reset or a different deployment may cause this; the original receipt remains available below."}</p>`}
    <dl class="receipt-fields">${rows.map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value == null || value === "" ? "Not recorded" : value)}</dd></div>`).join("")}</dl>
  </section>`;
}

function renderCompliancePanelHtml(onChain) {
  if (!onChain) {
    return `<section class="compliance-panel"><div class="compliance-heading"><div><h3>On-chain Compliance Result</h3><p>${chainLookupError ? "The current chain is unavailable." : "This version was not found on the current chain."} Its on-chain compliance result cannot be loaded.</p></div><span class="compliance-status unavailable">Unavailable</span></div></section>`;
  }
  const compliance = onChain && onChain.compliance
    ? onChain.compliance
    : { status: "pending" };
  const status = compliance.status || "pending";
  const progress = status === "uploading"
    ? `${compliance.bytesStored || 0} / ${compliance.bundleSize || 0} bytes`
    : status === "finalized"
      ? `${compliance.bundleSize || 0} bytes in ${compliance.chunkCount || 0} chunk(s)`
      : "Waiting for the off-chain P1/P2/P3 pipeline";
  return `<section class="compliance-panel">
    <div class="compliance-heading">
      <div>
        <h3>On-chain Compliance Result</h3>
        <p>${escapeHtml(progress)}</p>
      </div>
      <span class="compliance-status ${escapeHtml(status)}">${escapeHtml(complianceStatusLabel(status))}</span>
    </div>
    <div class="compliance-content" data-compliance-content>
      ${status === "finalized"
        ? "Downloading and verifying the on-chain bundle..."
        : status === "uploading"
          ? "The local result is complete and its chunks are being uploaded."
          : "The result will appear after P1, P2, and P3 finish."}
    </div>
  </section>`;
}

async function hydrateCompliancePanel(container, onChain) {
  const target = container.querySelector("[data-compliance-content]");
  const compliance = onChain && onChain.compliance;
  if (!target || !onChain || !compliance || compliance.status !== "finalized") {
    return;
  }
  try {
    const response = await fetch(`/api/compliance/${encodeURIComponent(onChain.recordKey)}`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "Could not load the compliance result");
    }
    const manifest = payload.manifest || {};
    const files = payload.files || [];
    target.innerHTML = `
      <dl class="compliance-audit-grid">
        <div><dt>Verified</dt><dd>${payload.verified ? "yes" : "no"}</dd></div>
        <div><dt>Bundle hash</dt><dd>${escapeHtml(manifest.bundleHash || "")}</dd></div>
        <div><dt>Pipeline</dt><dd>${escapeHtml(manifest.pipelineVersion || "")}</dd></div>
        <div><dt>Model</dt><dd>${escapeHtml(manifest.model || "")}</dd></div>
        <div><dt>P3 mode</dt><dd>${escapeHtml(manifest.p3Mode || "")}</dd></div>
        <div><dt>Uploader</dt><dd>${escapeHtml(compliance.submitter || "")}</dd></div>
      </dl>
      <a class="compliance-download" href="${escapeHtml(payload.downloadUrl || "")}" download>Download verified result bundle</a>
      <div class="compliance-files">
        ${files.map((file) => `<details>
          <summary>${escapeHtml(file.name)} · ${escapeHtml(String(file.size))} bytes</summary>
          <pre>${escapeHtml(file.content || "")}</pre>
        </details>`).join("")}
      </div>
    `;
  } catch (error) {
    target.textContent = formatError(error);
    target.classList.add("compliance-error");
  }
}

function complianceStatusLabel(status) {
  if (status === "unavailable") return "Unavailable";
  if (status === "finalized") return "Finalized on chain";
  if (status === "uploading") return "Uploading";
  return "Pending analysis";
}

function renderMetadataGroupHtml(title, rows) {
  return `
    <details class="metadata-group">
      <summary><h3>${escapeHtml(title)}</h3><span>${rows.length} fields</span></summary>
      <dl>
        ${rows.map(([label, value, evidenceKey]) => `
          <div>
            <dt>${escapeHtml(label)}${reviewFieldHelp[evidenceKey] ? `<small>${escapeHtml(reviewFieldHelp[evidenceKey])}</small>` : ""}</dt>
            <dd>
              <span>${escapeHtml(displayValue(value))}</span>
              ${renderDetailsHtml(evidenceKey)}
              ${renderAssessmentHtml(evidenceKey, value)}
              ${renderEvidenceHtml(evidenceKey)}
            </dd>
          </div>
        `).join("")}
      </dl>
    </details>
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

function metadataGroups(data, auditTitle = "On-chain Audit") {
  return [
    ["Identity", [
      ["Publisher", data.publisherEntity, ""],
      ["Service", data.serviceName, ""],
      ["Effective Date", data.effectiveDate, ""],
      ["Policy Version", data.policyVersion, ""],
    ]],
    [auditTitle, [
      ["Document Hash", data.documentHash, ""],
      ["Metadata Hash", data.metadataHash, ""],
      ["Document Chunk Commitment", data.documentChunkCommitment, ""],
      ["Metadata Chunk Commitment", data.metadataChunkCommitment, ""],
      ["Document Bytes / Chunks", `${data.documentSize || 0} / ${data.documentChunkCount || 0}`, ""],
      ["Metadata Bytes / Chunks", `${data.metadataSize || 0} / ${data.metadataChunkCount || 0}`, ""],
      ["Registrant", data.registrant, ""],
      ["Registered At", data.registeredAt, ""],
      ["Previous Record", data.previousRecordKey, ""],
    ]],
    ["Data Collection", [
      ["Data Types", data.dataTypeTags, "dataTypeTags"],
      ["Data Sources", data.dataSourceTypes, "dataSourceTypes"],
      ["Collection Context", data.collectionContext, "collectionContext"],
      ["Processing Purpose", data.processingPurpose, "processingPurpose"],
      ["Permitted Usage", data.permittedUsage, "permittedUsage"],
    ]],
    ["Data Sharing", [
      ["Third-party Sources", data.thirdPartySources, "thirdPartySources"],
      ["Downstream Stakeholders", data.downstreamStakeholders, "downstreamStakeholders"],
      ["Third-party Purpose", data.thirdPartyPurpose, "thirdPartyPurpose"],
      ["Sharing Condition", data.sharingCondition, "sharingCondition"],
    ]],
    ["User Rights", [
      ["Consent Required", data.consentRequired, "consentRequired"],
      ["Opt-out Available", data.optOutAvailable, "optOutAvailable"],
      ["Deletion Available", data.deletionAvailable, "deletionAvailable"],
      ["Request Channel", data.requestChannel, "requestChannel"],
    ]],
    ["Retention and Security", [
      ["Retention Policy", data.retentionPolicy, "retentionPolicy"],
      ["Encryption Applied", data.encryptionApplied, "encryptionApplied"],
      ["Anonymisation", data.anonymisation, "anonymisation"],
    ]],
    ["Compliance", [
      ["Regulatory Framework", data.regulatoryFramework, "regulatoryFramework"],
      ["Cross-border Transfer", data.crossBorderTransfer, "crossBorderTransfer"],
      ["Child Data Involved", data.childDataInvolved, "childDataInvolved"],
    ]],
    ["Change and Accountability", [
      ["Change Summary", data.changeSummary, ""],
      ["Contact Channel", data.contactChannel, "contactChannel"],
      ["Risk Flags", data.riskFlags, "riskFlags"],
    ]],
  ];
}

function renderDetailsHtml(detailsKey) {
  if (!detailsKey) {
    return "";
  }
  const details = currentDetails && currentDetails[detailsKey];
  return details ? `<p class="metadata-details">${escapeHtml(details)}</p>` : "";
}

function renderEvidenceHtml(evidenceKey) {
  if (!evidenceKey) {
    return "";
  }
  const evidence = currentEvidence && currentEvidence[evidenceKey];
  const lines = reviewEvidenceLines(evidence);
  if (!lines.length) {
    return "";
  }
  return `<ul class="evidence-list">
    ${lines.map((line) => `<li><span>${escapeHtml(line)}</span><button type="button" class="evidence-jump" data-source-quote="${escapeHtml(line)}">View in policy ↗</button></li>`).join("")}
  </ul>`;
}

function jumpToSavedEvidence(event, container) {
  const button = event.target.closest("[data-source-quote]");
  if (!button) return false;
  const fullText = container.querySelector(".raw-preview details");
  if (!fullText) return true;
  fullText.open = true;
  locateEvidence(
    fullText.querySelector(".saved-policy-text"),
    button.dataset.sourceQuote,
    container.querySelector(".source-navigation-status"),
  );
  return true;
}

function renderAssessmentHtml(assessmentKey, value) {
  if (!assessmentKey) {
    return "";
  }
  const assessment = assessmentForValue(assessmentKey, value);
  if (!assessment) {
    return "";
  }
  const status = assessment.reviewStatus || "auto_extracted";
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
