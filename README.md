# Privacy Policy Machine

A runnable prototype for registering, querying, updating, and verifying privacy policies with a small web UI, SQLite storage, and a deployed Solidity registry.

## Features

- Create a policy by entering an application name and uploading a policy file.
- Automatically use the upload time as the policy version.
- Put the complete raw policy bytes and canonical metadata JSON in transaction calldata, while storing their hashes and core identity fields in contract storage.
- Query policies by application name and view the full policy text.
- Verify a policy by entering the application name and uploading a file or pasting policy text.
- Switch between prototype developers in the top bar.
- Update only the policies uploaded by the selected developer.
- Prevent duplicate policy content from being registered twice.
- Choose fast, AI-assisted, or manual-review registration and retain that method with each database record.

## Project Structure

- `web/static/index.html`: browser UI.
- `web/static/app.js`: frontend workflow and API calls.
- `web/static/styles.css`: UI styling.
- `server/app.py`: HTTP server, API routes, policy registration, query, update, and verification.
- `server/storage.py`: SQLite storage layer.
- `server/processor.py`: simple metadata extraction, hash generation, and report generation.
- `server/llm_models.py`: local LLM result models and domain errors.
- `server/llm_client.py`: Ollama client, prompt, and connection configuration.
- `server/llm_processor.py`: policy chunking, evidence validation, retries, and result aggregation.
- `server/blockchain.py`: Web3 client that sends transactions to and reads records from the deployed contract.
- `contracts/TrustedPolicyRegistry.sol`: Solidity policy registry used by the web application.
- `scripts/deploy-contract.js`: deploys the registry to the configured RPC network.
- `offchain-listener/listener.js`: listens for successful on-chain policy registrations and starts off-chain work.
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

The manual multi-terminal sequence below is only needed when debugging an
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
sends a transaction to this deployed Solidity contract before its SQL row is
saved. Keep the chain running while using the application.

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
3. Choose Fast Upload, AI Upload, or Manual Upload.
4. AI and Manual uploads open a review page before anything is persisted; Fast Upload registers immediately.
5. The app registers the approved policy with a generated UUID and an upload-time policy version.
6. Use `Query` to search by application name. Matching records appear in `Registered Records`, and the latest match's full policy text is shown in the Query panel.
7. Use `Verification` by entering the application name and either uploading a policy file or pasting policy text.
8. Use `Update Policy` to update an existing policy. The dropdown only shows policies uploaded by the currently selected developer.

## API

### `POST /api/policies`

Create and register a new policy.

This is the Fast Upload route. It runs keyword analysis and persists immediately with `upload_method=fast`.

Required multipart fields:

- `applicationName`: application name entered by the user.
- `developer`: current prototype developer, supplied by the UI developer switcher.
- `rawFile`: uploaded policy file.

Optional multipart fields:

- `policyUrl`: source URL for the published policy.
- `effectiveDate`: effective date stated by the policy.
- `changeSummary`: summary of what changed, mainly used during updates.

The server generates:

- `policyId`: UUID used only by the off-chain database/API.
- `policyVersion`: upload time.
- `hashCode`: SHA-256 hash of the policy text, used only off-chain for duplicate detection and reporting.
- EVM transaction and block data returned by the deployed Solidity contract.

### `POST /api/analyze`

Run local Ollama analysis without keyword-rule extraction and return a review draft. Nothing is persisted. The response uses `uploadMethod=ai` and `requiresReview=true`.

### `POST /api/policies/manual`

Run keyword analysis and return a review draft. Nothing is persisted. The response uses `uploadMethod=manual` and `requiresReview=true`.

### `POST /api/policies/reviewed`

Register an AI or manually reviewed draft. Requires the original policy file, `uploadMethod`, and `metadataJson`. The server assigns the final ID, version, hash, and identity metadata.

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

The server only allows the update when the selected developer matches the latest record's developer.

### `POST /api/verify`

Verify submitted policy content against the latest trusted record for an application.

Required multipart fields:

- `applicationName`: application name to verify.
- `rawFile` or `rawText`: uploaded file or pasted policy text.

Verification compares:

- submitted policy text against the latest SQL record after normalizing case, whitespace, and punctuation.
- SQL and recovered-calldata policy hashes against the contract's `documentHash`.
- SQL and recovered canonical metadata hashes against the contract's `metadataHash`.
- publisher, service name, and upload-time version against the contract record.

### `POST /api/analyze`

Analyze policy text with a local Ollama model. This preview endpoint does not
write to SQLite or the blockchain.

Accepted JSON fields:

- `rawText`: pasted privacy-policy text.

Alternatively, submit multipart form data with a `rawFile` upload. The response
contains structured results for `sharing_condition`, `retention_policy`,
`cross_border_transfer`, and `child_data_involved`, along with evidence and
review/error information.

The default model is `qwen3.5:9b`. It can be changed with
`OLLAMA_MODEL`; timeout and retry count can be changed with
`OLLAMA_TIMEOUT_SECONDS` and `OLLAMA_RETRIES`.

```bash
ollama pull qwen3.5:9b
curl http://127.0.0.1:8000/api/analyze \
  -H 'Content-Type: application/json' \
  -d '{"rawText":"We retain account records for seven years."}'
```

## Data Notes

- Application name is currently stored in the database column `policy_name` for compatibility with the earlier prototype.
- `policyVersion` is no longer entered by the user. It is generated from upload time.
- The developer switcher is only a prototype display control. There is no login system yet.
- If incoming policy content already exists, the API returns `409 Conflict` and does not write a new SQL or chain record.
- `sources/dataset/` is ignored by Git so the local dataset is not uploaded.

## On-chain Record Class

```text
TrustedPolicyRecord
- documentHash: bytes32 (SHA-256 of the exact raw file bytes)
- metadataHash: bytes32 (SHA-256 of canonical metadata JSON)
- publisherEntity: string
- serviceName: string
- policyVersion: string
- effectiveDate: string
- registrant: address
- registeredAt: uint64
- previousRecordKey: bytes32
- hasPreviousReference: bool
```

The complete raw file and metadata JSON are included in the successful registration transaction's calldata but are not copied into contract storage. The contract computes and permanently stores both hashes. The API's UUID `policyId` remains off-chain.

## Independent calldata audit

An auditor needs the chain RPC URL, contract address, transaction hash, and matching contract ABI. The audit verifies the receipt, destination contract, called function, sender, event, storage record, both content hashes, and version identity without trusting SQLite:

```bash
.venv/bin/python scripts/audit-registration.py \
  0xTransactionHash \
  --rpc-url http://127.0.0.1:8545 \
  --contract-address 0xContractAddress \
  --output-dir recovered-audit
```

The optional output directory receives the exact `raw-file.bin` bytes and canonical `metadata.json` recovered from transaction calldata. The same summary is available while the server is running:

```text
GET /api/audit/{txHash}
```

Calldata is public. Do not register secrets or personal information that should not be publicly recoverable. A restarted `npm run dev` creates a new ephemeral Hardhat chain, so durable third-party audit requires a persistent network.

## Off-chain Event Listener (Experimental)

Every successful `registerTrustedPolicyRecord` transaction emits the contract's
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

When a policy is registered, the listener currently prints the UTC detection
time and ID:

```text
[2026-08-17T02:30:45.123Z] policyId=0x...
```

Replace the body of `callOffchainTool` in `listener.js` with the real tool call
when the tool is available. The listener uses provider polling, so both local
and hosted HTTP JSON-RPC endpoints work.

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
The API response includes its real transaction and block data. At the same time,
Terminal 2 prints the event detection time and the same on-chain policy ID.
Restarting the Hardhat node creates a fresh chain, so deploy the contract again
and use its new address after every restart.
