# Privacy Policy Machine

A local web application backed by a registry on Base Mainnet (chain ID `8453`). Policy files, metadata, and compliance ZIPs are stored in public contract storage.

## Features

- Create a policy by entering an application name and uploading a policy file.
- Automatically use the upload time as the policy version.
- Store the complete raw policy bytes and canonical metadata JSON in ordered chunks in L2 contract storage.
- Query policies by application name and view the full policy text.
- Verify a policy by entering the application name and uploading a file or pasting policy text.
- Switch between prototype developers in the top bar.
- Update only the policies uploaded by the selected developer.
- Prevent duplicate policy content through the application; the contract rejects repeated chunk commitments.
- Analyze every new or updated policy with the local AI model and require human review before registration.

## Project Structure

- `web/static/index.html`: browser UI.
- `web/static/app.js`: frontend workflow and API calls.
- `web/static/styles.css`: UI styling.
- `server/app.py`: HTTP server, API routes, policy registration, query, update, and verification.
- `server/processor.py`: AI metadata constraints, hash generation, validation, and report generation.
- `server/llm_models.py`: local LLM result models and domain errors.
- `server/llm_client.py`: Ollama client, prompt, and connection configuration.
- `server/llm_processor.py`: policy chunking, evidence validation, retries, and result aggregation.
- `server/blockchain.py`: Web3 client for wallet transaction preparation, contract-storage reads, and independent content audits.
- `contracts/TrustedPolicyRegistry.sol`: Solidity policy registry used by the web application.
- `config/base-mainnet.env`: local, Git-ignored file for the Base RPC, contract, wallet, and AI account settings.
- `scripts/base-mainnet.js`: explicit Base Mainnet deployment, authorization, and read-only status commands.
- `offchain-listener/listener.js`: listens for successful on-chain policy registrations, reconstructs the registered raw file, and runs compliance P1/P2/P3.
- `compliance tool/run_compliance.py`: adapts one on-chain raw file to the directory-based P1/P2/P3 command interfaces.
- `compliance tool/P1/high_risk_detection.py`: classifies the policy with the GPT API and selects the P3 checklist.
- `compliance tool/P2/information_extract.py`: extracts policy information with the GPT API.
- `compliance tool/P3/evaluate_checklist.py`: evaluates the extracted information against the compliance checklist.

`compliance tool/` is intentionally Git-ignored and kept only on this machine.
A new checkout needs a separate local copy of that directory for automatic
P1/P2/P3 analysis and on-chain compliance report uploads.

## Run locally with Base Mainnet

Install the local web, contract, and listener dependencies:

```bash
npm install
cd offchain-listener && npm install && cd ..
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
npm run contract:compile
ollama pull qwen3.5:9b
```

Copy `config/base-mainnet.env.example` to `config/base-mainnet.env` if the filled file does not already exist. This is the **one local file to fill in** for chain access and account settings. It is excluded from Git. Use a Base Mainnet HTTPS RPC that supports `eth_getLogs` with enough request capacity for chunk reads and event polling. The public `https://mainnet.base.org` endpoint can return HTTP 429 even for small event queries; use a provider endpoint for reliable operation. `EXPECTED_CHAIN_ID` must remain `8453`.

| Setting | What to put in it |
| --- | --- |
| `RPC_URL` | Base Mainnet HTTPS RPC endpoint. An endpoint with an API token is acceptable because this file is ignored. |
| `PUBLISHER_WALLETS_JSON` | Map each exact developer name shown in the UI to that developer's public wallet address. Developers connect these wallets in the browser and pay their own Base ETH fees. No developer private keys are stored by this application. |
| `BASE_DEPLOYER_PRIVATE_KEY` | Dedicated deployment/admin wallet private key, used only by the explicit deployment command. It pays for contract creation and initial authorization transactions. |
| `BASE_OWNER_ADDRESS` | Optional future owner, such as a multisig. The deployment wallet remains owner until that address calls `acceptOwnership()`. |
| `COMPLIANCE_PRIVATE_KEY` | Dedicated listener wallet private key. This wallet pays Base ETH to store compliance ZIPs and must be authorized by the contract. |
| `OPENAI_API_KEY` | API key used by the P1/P2/P3 compliance pipeline. |
| `CONTRACT_ADDRESS`, `CONTRACT_DEPLOYMENT_BLOCK`, `CONTRACT_RUNTIME_CODE_HASH` | Filled automatically by the deployment command after its transactions are verified, or manually for an existing verified deployment. Local startup requires the runtime code hash and checks it against Base. |

Fund the deployment/admin wallet for contract setup, each developer wallet for its own policy uploads, and the separate platform compliance wallet for ZIP uploads. These are **real Base ETH transactions**. The complete policy text, metadata, and compliance report become publicly recoverable contract data; only upload material intended to be public.

### Deploy once, explicitly

For a new deployment, fill the RPC, developer addresses, deployment key, and compliance key, then run:

```bash
npm run base:status
npm run contract:compile
npm run base:deploy
```

If `CONTRACT_ADDRESS` is already set, the contract is already configured. Run
`npm run base:status` to check it and skip `npm run base:deploy`.

`base:status` reads chain state and balances without sending transactions. `base:deploy` is the only deployment command and requires chain ID `8453`; `npm run dev` never deploys or authorizes. Deployment creates the registry with the deployer as initial owner, registers each `PUBLISHER_WALLETS_JSON` address, authorizes the compliance wallet, and optionally proposes ownership transfer to `BASE_OWNER_ADDRESS`. The target owner must call `acceptOwnership()` separately. The command records signed transactions before broadcast in Git-ignored `data/base-mainnet/pending-transactions.json`, allowing an interrupted run to resume without producing another contract. Verified transaction hashes and code hashes are saved in `data/base-mainnet/deployment.json`.

After deployment, changing a developer wallet in the config file also requires
the current contract owner to call `setPublisherOwner(developerName, newAddress)`
on Base Mainnet. Changing only the local file does not change the on-chain role;
`npm run dev` checks that they match before starting.

If `data/base-mainnet/deploy.lock` remains after a crash, inspect the pending transaction hashes on BaseScan and confirm no deployment process remains before deleting that lock. Do not delete the transaction journal to retry a pending deployment.

### Start the local services

```bash
npm run dev
```

This command compiles the ABI, checks that the RPC is Base Mainnet, verifies the deployed contract and configured wallet authorizations, and starts the local Python web server and compliance event listener. It does not start a local blockchain. Developers connect their own Base wallet in the web UI and approve policy transactions there. The listener signs compliance uploads with `COMPLIANCE_PRIVATE_KEY`. Press `Ctrl+C` to stop the local processes; Base data remains on-chain.

The server prints its local URL, normally `http://127.0.0.1:8000`. If that port is busy, it chooses the next available port. `PORT` can be set in `config/base-mainnet.env` to request a specific port.

## UI Workflow

1. Choose a developer from the top-bar `Developer` selector.
2. In `Create Policy`, enter an `Application Name` and upload a policy file.
3. Submit the file for local AI analysis. Nothing is persisted during analysis.
4. Review and edit the AI-extracted metadata, details, and evidence.
5. Connect the wallet assigned to the selected developer. Confirm the review, switch the wallet to Base Mainnet if prompted, and approve each manifest, content-chunk, and finalization transaction. The developer wallet pays the Base ETH fees. If interrupted, reopen the draft and reselect the identical file to resume after its SHA-256 is checked.
6. Use `Query` to search by application name. `Latest Policies` shows the latest version of each policy, and the latest match's full policy text is shown in the Query panel. Click `Previous versions` to inspect older uploads, including the initial version, or `Latest version` to return to the current upload.
7. Use `Verification` by entering the application name and either uploading a policy file or pasting policy text.
8. Use `Update Policy` to analyze and review a new version. The dropdown only shows policies uploaded by the currently selected developer.

## API

### `POST /api/analyze`

Analyze policy text with the local Ollama model and return a review draft. This
preview endpoint does not write to the blockchain. Its response includes
`requiresReview=true`.

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

### `GET /api/config`

Return the public Base chain ID, deployed contract address, and developer wallet
addresses required by the browser. Private keys and private RPC credentials are
never returned.

### `POST /api/policies/prepare`

Prepare calls for a reviewed policy upload. The server validates the draft,
checks the configured developer wallet, and returns the exact contract calls
remaining for that version. It does not sign or send transactions. The browser
wallet submits each call on Base Mainnet.

Required multipart fields are `workflow` (`create` or `update`), `developer`,
`walletAddress`, the original `rawFile`, and approved `metadataJson`. A create
also needs `applicationName`; an update needs the existing `policyId`. Optional
fields include `policyUrl`, `effectiveDate`, and `changeSummary`.

### `POST /api/policies/complete`

After the wallet transaction receipts succeed, send JSON containing the
`recordKey` returned by `/prepare`. The server reads the finalized contract
record and returns the policy, metadata, report, and chain details. A partially
uploaded version cannot complete; repeat `/prepare` with the same draft and
file to obtain only the remaining calls.

### `GET /api/policies`

List finalized Base Mainnet policy records, rebuilt from contract events and
verified contract content.

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

### `GET /api/records/{recordKey}/raw`

Download the exact original file bytes reconstructed from contract storage after
checking the file hash, length, and chunk commitment. This is useful for files
that cannot be represented faithfully as UTF-8 text in a JSON response.

### `POST /api/verify`

Verify submitted policy content against the latest trusted record for an application.

Required multipart fields:

- `applicationName`: application name to verify.
- `rawFile` or `rawText`: uploaded file or pasted policy text.

Verification compares:

- submitted policy text against the latest on-chain record after normalizing case, whitespace, and punctuation.
- submitted bytes and the on-chain hash against content reconstructed from contract storage.
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

- Application name is stored as `serviceName` in the contract and `policyName` in the API response.
- API payloads and canonical metadata JSON use camelCase keys throughout.
- `metadataDetails` preserves a concise explanation for every reviewable metadata field; `metadataEvidence` retains the supporting policy quotations.
- `policyVersion` is no longer entered by the user. It is generated from upload time.
- The developer switcher selects a publisher label. The browser wallet must match the address authorized on-chain for that label.
- If incoming policy content already exists, the API returns `409 Conflict` and does not create a new chain record.
- `sources/dataset/` is ignored by Git so the local dataset is not uploaded.
- `data/policies.db` is preserved as an archive. The application does not read it or import its records to Base Mainnet.

## Chunked L2 Storage

Policy registration stores all bytes on Base Mainnet:

1. `beginPolicyRegistration` creates a pending manifest containing identity,
   expected byte sizes, and declared SHA-256 hashes.
2. `appendDocumentChunk` and `appendMetadataChunk` write exact byte slices to
   contract storage in strictly increasing index order. Each successful chunk is
   committed by `keccak256(previousCommitment, index, byteLength, sha256(chunk))`.
3. `finalizePolicyRegistration` succeeds after both declared byte lengths are
   stored. Only then is the record added to the public version index. The chain
   commits each chunk and its order and prevents a duplicate document with the
   same chunk sequence. The web server and independent auditors reconstruct the
   complete bytes and check the manifest's whole-file SHA-256.

Chunk size is bounded by the contract's 24 KiB per-chunk ceiling. The browser
wallet prompts the developer for each policy transaction. To start with smaller
chunks, set the following in `config/base-mainnet.env`:

```bash
ONCHAIN_CHUNK_BYTES=4096
```

This contract accepts at most 256 KiB of original policy bytes and 128 KiB of
metadata JSON per version. Preparation rejects larger files before the browser
wallet sends a transaction.

Pending uploads are not visible as trusted records until finalization. Keep the
same reviewed draft and wallet available when resuming an interrupted upload.

The LLM uses a separate, overlapping text-chunk process for model context. LLM
chunks are character slices; on-chain chunks are exact bytes and must not be
interchanged.

## Off-chain compliance processing

After `TrustedPolicyRecordRegistered` is confirmed, the listener reconstructs
and verifies the exact on-chain `rawFile`. An external adapter places it in an
isolated temporary input directory and runs the directory-based P1, P2, and P3
commands. The local result directory is:

```text
data/compliance-results/8453/<contractAddress>/<recordKey>/
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

The GPT API key is read from `OPENAI_API_KEY` in the Git-ignored
`config/base-mainnet.env` file.

The listener defaults to `COMPLIANCE_HIGH_RISK=auto`, so P1's classification
selects the high- or low-risk P3 checklist. Set it to `yes` or `no` to override
that selection. `npm run dev` uses the dedicated, contract-authorized wallet in
`COMPLIANCE_PRIVATE_KEY`. `COMPLIANCE_GPT_MODEL`, `COMPLIANCE_PYTHON_PATH`,
`COMPLIANCE_OUTPUT_DIR`, `COMPLIANCE_CHUNK_BYTES`, and
`COMPLIANCE_MAX_BUNDLE_BYTES` can override the corresponding defaults. The
default bundle limit is 1 MiB.
The contract also caps a compliance ZIP at 1 MiB; an oversized result is not
truncated or registered. The listener records an error and retries after the
underlying output or contract limit is addressed.
If P1, P2, or P3 fails, the listener pauses analysis to avoid repeated paid
model calls. Fix the error and restart `npm run dev` to retry the same policy.
Once a bundle exists locally, upload retries reuse it without calling the model.

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
chunks arrive. The server supplies a whole-content SHA-256 claim in the pending
manifest, then reconstructs the finalized storage and verifies that claim. The
contract cannot prove the whole-file SHA-256 at these file limits without
exceeding gas limits; direct contract callers can submit a false claim, which
the server and independent audit reject. Duplicate prevention on-chain uses the
chunk commitment computed from actual submitted bytes.
The API's UUID `policyId` remains an application identifier inside canonical
metadata; `recordKey` is the on-chain identifier for a policy version.

## Independent on-chain storage audit

An auditor needs the chain RPC URL, contract address, a finalized `recordKey` or
finalization transaction hash, and the matching contract ABI. The audit reads all
chunks from contract storage and verifies the receipt, destination contract,
finalization call, sender, event, sizes, counts, both hashes, and both ordered
commitments directly from Base Mainnet:

```bash
.venv/bin/python scripts/audit-registration.py \
  0xRecordKeyOrFinalizationTransactionHash \
  --rpc-url https://your-provider.example/base-mainnet \
  --contract-address 0xContractAddress \
  --deployment-block 12345678 \
  --output-dir recovered-audit
```

The optional output directory receives the exact `raw-file.bin` bytes and
canonical `metadata.json` reconstructed from contract storage. The same summary
is available while the server is running:

```text
GET /api/audit/{recordKey-or-finalization-txHash}
```

Contract storage is public. Do not register secrets or personal information that
should not be publicly recoverable. Use the same Base Mainnet contract address
for independent audits after restarting the local services.

## Off-chain Event Listener

Every successful `finalizePolicyRegistration` transaction emits the contract's
`TrustedPolicyRecordRegistered` event. Its indexed `recordKey` is the unique
on-chain ID for that policy version. The UUID called `policyId` by the local API
is stored inside the on-chain metadata JSON.

The normal `npm run dev` command starts the listener. To run it alone after
deploying `TrustedPolicyRegistry.sol` and filling `config/base-mainnet.env`:

```bash
cd offchain-listener
npm install
npm start
```

When a policy is registered, the listener prints the UTC detection time,
runs P1/P2/P3, and uploads the verified result bundle:

```text
[2026-09-21T02:30:45.123Z] processing compliance for Example (0x...)
[2026-09-21T02:30:45.123Z] compliance bundle finalized for 0x...
```

The listener uses provider polling with three confirmations by default. It signs
with `COMPLIANCE_PRIVATE_KEY` and requires that wallet to be authorized by the
contract owner. Its local cursor is stored in Git-ignored
`data/base-mainnet/listener-state.json` when started through `npm run dev`.

### Complete web-to-contract event test

Run `npm run dev`, connect a configured developer's wallet to Base Mainnet in
the browser, and upload a small policy that is safe to publish. The wallet
approves the policy manifest, content chunks, and finalization. After three
confirmations, the listener detects the registration,
runs P1/P2/P3, and uploads the report ZIP with the compliance wallet. The
Records page shows the result and lets you download the complete ZIP. Every
transaction incurs real Base ETH fees.
