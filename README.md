# Privacy Policy Machine

A runnable prototype for registering, querying, updating, and verifying privacy policies with a small web UI, SQLite storage, and a deployed Solidity registry.

## Features

- Create a policy by entering an application name and uploading a policy file.
- Automatically use the upload time as the policy version.
- Store the complete raw policy bytes and canonical metadata JSON in ordered chunks in L2 contract storage.
- Query policies by application name and view the full policy text.
- Verify a policy by entering the application name and uploading a file or pasting policy text.
- Switch between prototype developers in the top bar.
- Update only the policies uploaded by the selected developer.
- Prevent duplicate policy content from being registered twice.
- Analyze every new or updated policy with the local AI model and require human review before registration.

## Project Structure

- `web/static/index.html`: browser UI.
- `web/static/app.js`: frontend workflow and API calls.
- `web/static/styles.css`: UI styling.
- `server/app.py`: HTTP server, API routes, policy registration, query, update, and verification.
- `server/storage.py`: SQLite storage layer.
- `server/processor.py`: AI metadata constraints, hash generation, validation, and report generation.
- `server/llm_models.py`: local LLM result models and domain errors.
- `server/llm_client.py`: Ollama client, prompt, and connection configuration.
- `server/llm_processor.py`: policy chunking, evidence validation, retries, and result aggregation.
- `server/blockchain.py`: Web3 client for resumable chunk uploads, contract-storage reads, and independent content audits.
- `contracts/TrustedPolicyRegistry.sol`: Solidity policy registry used by the web application.
- `scripts/deploy-contract.js`: deploys the registry to the configured RPC network.
- `offchain-listener/listener.js`: listens for successful on-chain policy registrations, reconstructs the registered raw file, and runs compliance P1/P2/P3.
- `compliance tool/run_compliance.py`: adapts one on-chain raw file to the directory-based P1/P2/P3 command interfaces.
- `compliance tool/P1/high_risk_detection.py`: classifies the policy with the GPT API and selects the P3 checklist.
- `compliance tool/P2/information_extract.py`: extracts policy information with the GPT API.
- `compliance tool/P3/evaluate_checklist.py`: evaluates the extracted information against the compliance checklist.
- `data/policies.db`: local SQLite database.

## Run locally

Install and compile once:

```bash
npm install
npm run contract:compile
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

After that, the normal startup command is:

```bash
npm run dev
```

This single command compiles the contract, starts a fresh Hardhat chain,
deploys the contract, passes its RPC URL and address to the event listener and
Python web server, and starts both services. Press `Ctrl+C` once to stop all of
them.

The multi-terminal sequence below is only needed when debugging an
individual component.

Then use three terminals. Hardhat is the real local EVM used by the web app;
restarting it clears the local chain and requires another deployment.

Terminal 1 — start the chain:

```bash
npm run chain
```

Terminal 2 — deploy, then copy the values printed by this command:

```bash
npm run contract:deploy
```

Terminal 3 — export those values and start the web server:

```bash
export RPC_URL=http://127.0.0.1:8545
export CONTRACT_ADDRESS=0xAddressPrintedByDeploy
export CONTRACT_DEPLOYMENT_BLOCK=1
.venv/bin/python -m server.app
```

Every create, reviewed registration, and update submitted in the web UI now
sends a manifest transaction, one transaction per content chunk, and a finalization
transaction before its SQL row is saved. Keep the chain running while using the
application.

The server tries `http://127.0.0.1:8000` first. If port `8000` is already in use, it automatically chooses the next available port and prints the URL, for example:

```text
Privacy Policy Machine running at http://127.0.0.1:8001
```

Open the printed URL in your browser.

You can also force a port:

```bash
PORT=8002 .venv/bin/python -m server.app
```

## UI Workflow

1. Choose a developer from the top-bar `Developer` selector.
2. In `Create Policy`, enter an `Application Name` and upload a policy file.
3. Submit the file for local AI analysis. Nothing is persisted during analysis.
4. Review and edit the AI-extracted metadata, details, and evidence.
5. Confirm the review to upload the content chunks and finalize the policy with the UUID and upload-time version assigned to the review draft.
6. Use `Query` to search by application name. Matching records appear in `Registered Records`, and the latest match's full policy text is shown in the Query panel.
7. Use `Verification` by entering the application name and either uploading a policy file or pasting policy text.
8. Use `Update Policy` to analyze and review a new version. The dropdown only shows policies uploaded by the currently selected developer.

## API

### `POST /api/analyze`

Analyze policy text with the local Ollama model and return a review draft. This
preview endpoint does not write to SQLite or the blockchain. Its response uses
`uploadMethod=ai` and `requiresReview=true`.

Required multipart fields:

- `applicationName`: application name entered by the user.
- `developer`: current prototype developer, supplied by the UI developer switcher.
- `rawFile`: uploaded policy file.

Optional multipart fields:

- `policyUrl`: source URL for the published policy.
- `effectiveDate`: effective date stated by the policy.

The structured response includes a stable draft `policyId` and `policyVersion`,
extracted values, evidence, details, and review flags. Reusing that reviewed draft
allows an interrupted on-chain upload to resume. `permittedUsage` is extracted
independently from `processingPurpose`.

### `POST /api/policies/reviewed`

Register an AI-reviewed draft. Required multipart fields are `applicationName`,
`developer`, the original `rawFile`, and the approved `metadataJson`. The server
validates the draft ID and upload-time version assigned by `/api/analyze`, then
adds the hashes and finalized identity metadata.

### `GET /api/policies`

List stored policy records.

Optional query parameter:

- `applicationName`: filters records by application name.

Example:

```text
/api/policies?applicationName=ExampleApp
```

### `GET /api/policies/manageable`

List the latest policy records available to the update selector.

Optional query parameter:

- `developer`: filters records to policies uploaded by that developer.

Example:

```text
/api/policies/manageable?developer=alice
```

### `GET /api/policies/{policyId}`

Read the latest stored policy for a policy ID together with the matching Solidity contract record.

### `POST /api/policies/update`

Update an existing policy ID with a new uploaded file.

Required multipart fields:

- `policyId`: existing policy ID.
- `developer`: current prototype developer.
- `rawFile`: new uploaded policy file.
- `metadataJson`: AI-extracted metadata approved on the review page.

The server only allows the update when the selected developer matches the latest
record's developer. Updates must pass through `/api/analyze` and human review
before this endpoint is called.

### `POST /api/verify`

Verify submitted policy content against the latest trusted record for an application.

Required multipart fields:

- `applicationName`: application name to verify.
- `rawFile` or `rawText`: uploaded file or pasted policy text.

Verification compares:

- submitted policy text against the latest SQL record after normalizing case, whitespace, and punctuation.
- submitted and SQL hashes against content reconstructed from contract storage.
- reconstructed document and metadata hashes, sizes, chunk counts, and ordered chunk commitments against the finalized contract record.
- publisher, service name, and upload-time version against the contract record.

### Local Ollama configuration

The default model is `qwen3.5:9b`. It can be changed with
`OLLAMA_MODEL`; timeout and retry count can be changed with
`OLLAMA_TIMEOUT_SECONDS` and `OLLAMA_RETRIES`.

```bash
ollama pull qwen3.5:9b
curl http://127.0.0.1:8000/api/analyze \
  -F applicationName=ExampleApp \
  -F developer=alice \
  -F rawFile=@privacy-policy.txt
```

## Data Notes

- Application name is stored in the SQL column `policyName`.
- Database records, API payloads, and canonical metadata JSON use camelCase keys throughout.
- `metadataDetails` preserves a concise explanation for every reviewable metadata field; `metadataEvidence` retains the supporting policy quotations.
- `policyVersion` is no longer entered by the user. It is generated from upload time.
- The developer switcher is only a prototype display control. There is no login system yet.
- If incoming policy content already exists, the API returns `409 Conflict` and does not write a new SQL or chain record.
- `sources/dataset/` is ignored by Git so the local dataset is not uploaded.

## Chunked L2 Storage

Registration is a three-stage protocol:

1. `beginPolicyRegistration` creates a pending manifest containing identity,
   expected byte sizes, and SHA-256 hashes.
2. `appendDocumentChunk` and `appendMetadataChunk` write exact byte slices to
   contract storage in strictly increasing index order. Each successful chunk is
   committed by `keccak256(previousCommitment, index, byteLength, sha256(chunk))`.
3. `finalizePolicyRegistration` succeeds only when both declared byte lengths
   have been stored. Only then is the record added to the public version index.

The server defaults to 8 KiB transactions and never exceeds the contract's
24 KiB per-chunk ceiling. Configure a smaller starting size for a target L2 with:

```bash
export ONCHAIN_CHUNK_BYTES=4096
```

Before sending a chunk, the server estimates its gas. If the estimate cannot fit,
the chunk is reduced and retried before any transaction is sent. If a request is
interrupted after confirmed chunks, submitting the same reviewed draft reads the
pending manifest, validates every stored prefix byte, and resumes at the next
index. Pending uploads are not visible as trusted records.

The LLM uses a separate, overlapping text-chunk process for model context. LLM
chunks are character slices; on-chain chunks are exact bytes and must not be
interchanged.

## Off-chain compliance processing

After `TrustedPolicyRecordRegistered` is confirmed, the listener reconstructs
and verifies the exact on-chain `rawFile`. An external adapter places it in an
isolated temporary input directory and runs the directory-based P1, P2, and P3
commands. The local result directory is:

```text
data/compliance-results/<recordKey>/
├── p1-risk.json
├── p2-extraction.json
├── p3-checklist.json
├── p3-checklist.md
├── compliance-manifest.json
├── compliance-bundle.zip
└── onchain-receipt.json
```

The deterministic ZIP contains the four complete P1/P2/P3 files. The listener
uploads that ZIP to the contract in resumable chunks, finalizes the one allowed
compliance result for the policy record, reconstructs it from contract storage,
and verifies its SHA-256 and ordered chunk commitment. If chain upload fails,
the next attempt reuses the local bundle without calling GPT again. If a
finalized result is replayed with no local files, the listener restores the
local files from the on-chain ZIP.

The GPT API key is read locally from
`data/gpt.zshrc`; that file can contain either the bare key or an
`OPENAI_API_KEY=...` assignment and is ignored by Git.

The listener defaults to `COMPLIANCE_HIGH_RISK=auto`, so P1's classification
selects the high- or low-risk P3 checklist. Set it to `yes` or `no` to override
that selection. `npm run dev` uses Hardhat account 1 as the dedicated,
contract-authorized compliance uploader. `COMPLIANCE_UPLOADER_ACCOUNT`,
`COMPLIANCE_GPT_MODEL`, `COMPLIANCE_PYTHON_PATH`, `COMPLIANCE_OUTPUT_DIR`,
`COMPLIANCE_CHUNK_BYTES`, `COMPLIANCE_MAX_BUNDLE_BYTES`, and `GPT_CONFIG_PATH`
can override the corresponding defaults. The default bundle limit is 1 MiB.

Solidity functions still use the `calldata` data-location keyword for external
parameters. This is only an EVM input type: the application no longer treats
historical transaction input as the persistent policy archive.

## On-chain Record Class

```text
TrustedPolicyRecord
- documentHash: bytes32 (SHA-256 of the exact raw file bytes)
- metadataHash: bytes32 (SHA-256 of canonical metadata JSON)
- documentChunkCommitment: bytes32
- metadataChunkCommitment: bytes32
- documentSize: uint64
- metadataSize: uint64
- documentChunkCount: uint32
- metadataChunkCount: uint32
- publisherEntity: string
- serviceName: string
- policyVersion: string
- effectiveDate: string
- registrant: address
- registeredAt: uint64
- previousRecordKey: bytes32
- hasPreviousReference: bool
```

The complete raw file and metadata JSON are permanently stored in the contract's
chunk mappings. The contract computes each chunk hash and ordered commitment as
chunks arrive. The server supplies the interoperable whole-content SHA-256 in the
pending manifest, then reconstructs the finalized storage and verifies that hash.
This avoids concatenating an arbitrarily large file inside one finalization call.
The API's UUID `policyId` remains an application identifier inside canonical
metadata; `recordKey` is the on-chain identifier for a policy version.

## Independent on-chain storage audit

An auditor needs the chain RPC URL, contract address, a finalized `recordKey` or
finalization transaction hash, and the matching contract ABI. The audit reads all
chunks from contract storage and verifies the receipt, destination contract,
finalization call, sender, event, sizes, counts, both hashes, and both ordered
commitments without trusting SQLite:

```bash
.venv/bin/python scripts/audit-registration.py \
  0xRecordKeyOrFinalizationTransactionHash \
  --rpc-url http://127.0.0.1:8545 \
  --contract-address 0xContractAddress \
  --output-dir recovered-audit
```

The optional output directory receives the exact `raw-file.bin` bytes and
canonical `metadata.json` reconstructed from contract storage. The same summary
is available while the server is running:

```text
GET /api/audit/{recordKey-or-finalization-txHash}
```

Contract storage is public. Do not register secrets or personal information that
should not be publicly recoverable. A restarted `npm run dev` creates a new
ephemeral Hardhat chain, so durable third-party audit requires a persistent L2.

## Off-chain Event Listener

Every successful `finalizePolicyRegistration` transaction emits the contract's
`TrustedPolicyRecordRegistered` event. Its indexed `recordKey` is the unique
on-chain ID for that policy version; this is the `policyId` printed by the
experimental listener. The UUID called `policyId` by the local API remains an
off-chain-only identifier.

Install and run the listener after deploying `TrustedPolicyRegistry.sol`:

```bash
cd offchain-listener
npm install
RPC_URL=http://127.0.0.1:8545 \
CONTRACT_ADDRESS=0xYourDeployedContractAddress \
npm start
```

When a policy is registered, the listener prints the UTC detection time,
runs P1/P2/P3, and uploads the verified result bundle:

```text
[2026-09-21T02:30:45.123Z] processing compliance for Example (0x...)
[2026-09-21T02:30:45.123Z] compliance bundle finalized for 0x...
```

The listener uses provider polling. The uploader must be authorized by the
contract owner. For manual local startup, either use the deployer account or set
the same `COMPLIANCE_UPLOADER_ACCOUNT` when deploying and running the listener.

### Complete web-to-contract event test

Install the root contract dependencies and compile once:

```bash
npm install
npm run contract:compile
```

Use four terminals. Keep the chain, listener, and web server running.

Terminal 1 — start the local Hardhat chain:

```bash
npm run chain
```

Terminal 2 — deploy the contract, copy the three `export` lines it prints, then
start the listener with those variables:

```bash
npm run contract:deploy
export RPC_URL=http://127.0.0.1:8545
export CONTRACT_ADDRESS=0xAddressPrintedByDeploy
export CONTRACT_DEPLOYMENT_BLOCK=1
cd offchain-listener
npm start
```

Terminal 3 — use the same three exported values and start the web server:

```bash
export RPC_URL=http://127.0.0.1:8545
export CONTRACT_ADDRESS=0xAddressPrintedByDeploy
export CONTRACT_DEPLOYMENT_BLOCK=1
.venv/bin/python -m server.app
```

Terminal 4 — open the URL printed by the server and create or update a policy.
The API response includes its finalization transaction, chunk transaction list,
and block data. At the same time,
Terminal 2 prints the event detection time, pipeline output, chunk upload, and
the same on-chain policy ID. The Records page shows pending/uploading/finalized
status, verifies the chain bundle, displays all four files, and downloads the
complete ZIP.
Restarting the Hardhat node creates a fresh chain, so deploy the contract again
and use its new address after every restart.
