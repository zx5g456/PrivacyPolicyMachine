# Privacy Policy Machine

A runnable prototype for a web + Python + blockchain workflow that registers privacy policy records and verifies them later.

## Architecture

- `web/static`: browser UI for developers and researchers/auditors.
- `server/app.py`: HTTP API, policy processing, SQL storage, and verification orchestration.
- `server/blockchain.py`: local append-only blockchain ledger that behaves like the on-chain smart contract interface.
- `contracts/TrustedPolicyRegistry.sol`: Solidity contract for a real on-chain deployment.
- `data/policies.db`: SQLite database, created on first run.
- `data/chain.json`: local chain ledger, created on first run.

## Run

```bash
python3 server/app.py
```

Then open:

```text
http://127.0.0.1:8000
```

## API

- `POST /api/policies`: upload a policy file, extract metadata, store SQL data, and register a trusted record.
- `GET /api/policies`: list stored policies. Pass `applicationName` to query by application name.
- `GET /api/policies/manageable`: list the latest manageable policy records for the update selector. Pass `developer` to show only policies uploaded by that developer.
- `GET /api/policies/{policyId}`: read one policy with latest chain registration.
- `POST /api/policies/update`: update an existing policy ID with developer ownership checking and a new file.
- `POST /api/verify`: submit an application name plus an uploaded file or policy text for comparison against that application's latest trusted SQL and chain record.

The `POST` routes accept `multipart/form-data` with:

- `policyId` for update. Creation generates this UUID automatically.
- `applicationName` for creation and verification. It is required and must be entered by the user.
- `developer` for creation and update. The prototype UI supplies this from a top-bar developer switcher, not from a login system.
- `rawFile` uploaded file
- `rawText` for verification when not uploading a file

The application name is stored in SQL as `policy_name` for compatibility with the prototype database. `policyVersion` is now generated automatically from the upload time and is not entered in the create, query, or update UI. If the incoming file hash already exists, the API returns `409 Conflict` and does not write SQL or chain data.

In this local prototype there is no login system yet. The top-bar developer switcher is only a display/prototype control used for filtering and update ownership.

## On-chain Data Class

```text
OnChainData
- rawFile: string
- policyId: string
- policyVersion: string optional
- hashCode: string optional
```
