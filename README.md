# Privacy Policy Machine

A runnable prototype for registering, querying, updating, and verifying privacy policies with a small web UI, SQLite storage, and a local append-only blockchain ledger.

## Features

- Create a policy by entering an application name and uploading a policy file.
- Automatically use the upload time as the policy version.
- Store policy metadata, analysis results, raw policy text, hash values, SQL records, and local chain transaction data.
- Query policies by application name and view the full policy text.
- Verify a policy by entering the application name and uploading a file or pasting policy text.
- Switch between prototype developers in the top bar.
- Update only the policies uploaded by the selected developer.
- Prevent duplicate policy content from being registered twice.

## Project Structure

- `web/static/index.html`: browser UI.
- `web/static/app.js`: frontend workflow and API calls.
- `web/static/styles.css`: UI styling.
- `server/app.py`: HTTP server, API routes, policy registration, query, update, and verification.
- `server/storage.py`: SQLite storage layer.
- `server/processor.py`: simple metadata extraction, hash generation, and report generation.
- `server/blockchain.py`: local append-only ledger that mirrors an on-chain registration flow.
- `contracts/TrustedPolicyRegistry.sol`: Solidity contract sketch for a real on-chain deployment.
- `data/policies.db`: local SQLite database.
- `data/chain.json`: local chain ledger.

## Run

From the project root:

```bash
python3 server/app.py
```

The server tries `http://127.0.0.1:8000` first. If port `8000` is already in use, it automatically chooses the next available port and prints the URL, for example:

```text
Privacy Policy Machine running at http://127.0.0.1:8001
```

Open the printed URL in your browser.

You can also force a port:

```bash
PORT=8002 python3 server/app.py
```

## UI Workflow

1. Choose a developer from the top-bar `Developer` selector.
2. In `Create Policy`, enter an `Application Name` and upload a policy file.
3. The app registers the policy with a generated UUID and an upload-time policy version.
4. Use `Query` to search by application name. Matching records appear in `Registered Records`, and the latest match's full policy text is shown in the Query panel.
5. Use `Verification` by entering the application name and either uploading a policy file or pasting policy text.
6. Use `Update Policy` to update an existing policy. The dropdown only shows policies uploaded by the currently selected developer.

## API

### `POST /api/policies`

Create and register a new policy.

Required multipart fields:

- `applicationName`: application name entered by the user.
- `developer`: current prototype developer, supplied by the UI developer switcher.
- `rawFile`: uploaded policy file.

The server generates:

- `policyId`: UUID.
- `policyVersion`: upload time.
- `hashCode`: SHA-256 hash of the policy text.
- local chain transaction and block data.

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

Read the latest stored policy for a policy ID together with the matching local chain record.

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

- submitted content hash against the latest SQL record for that application.
- SQL record hash against the local chain hash.
- policy ID and upload-time version against the local chain record.

## Data Notes

- Application name is currently stored in the database column `policy_name` for compatibility with the earlier prototype.
- `policyVersion` is no longer entered by the user. It is generated from upload time.
- The developer switcher is only a prototype display control. There is no login system yet.
- If incoming policy content already exists, the API returns `409 Conflict` and does not write a new SQL or chain record.
- `sources/dataset/` is ignored by Git so the local dataset is not uploaded.

## On-chain Data Class

```text
OnChainData
- rawFile: string
- policyId: string
- policyVersion: string optional
- hashCode: string optional
```
