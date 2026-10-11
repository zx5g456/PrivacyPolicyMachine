# RQ3 extraction experiment

This is a prepared experiment, not a set of measured results. It uses the 20
metadata fields in `server/processor.py` and 15 independent privacy-policy texts
listed in `policies.csv`. The source files are under `sources/dataset/`, which is
ignored by Git; keep them available to reproduce the experiment. The manifest
contains SHA-256 digests and the runner refuses changed files.

## Design

All configurations use identical policies, field labels, chunk boundaries,
JSON transport mode, model, decoding settings and scoring rules. C0 is the
shared base task and already asks for a minimal JSON object with optional
evidence slots. C1 adds detailed JSON structure rules, C2 adds an evidence-first
decision procedure, C3 adds cross-chunk checking at the merge stage, and C4
combines C1+C2+C3. C1–C3 are parallel single-strategy comparisons with C0. C4 is the
combined system. This is not a full factorial design, so interactions cannot
be isolated.

The default chunk size is 3,000 characters with 200 characters of overlap.
Three policies fit in one chunk and twelve need two chunks. A multi-chunk job
uses two extraction calls and one merge call, yielding 585 model calls in an
error-free run of 225 policy/configuration/repeat jobs. Retries can add calls.
C3 is identical to C0 on one-chunk
policies by design. Each model call and entire job has a wall-clock duration.
The command prints cumulative session time and a rough ETA while running.

`sources/q2_data/` contains synthetic revisions for the RQ2 integrity test;
the RQ3 manifest uses the independent `sources/dataset/` policy texts instead.

## Run

From the repository root, with dependencies installed:

```sh
PYTHONPATH=. .venv/bin/python -m rq3.run --dry-run
PYTHONPATH=. .venv/bin/python -m rq3.run --backend ollama --model qwen3.5:9b --out-dir rq3/results/main
```

The default model is the repository's local Ollama model. To use OpenAI instead,
set `OPENAI_API_KEY` in the environment and pass `--backend openai --model MODEL`.
For Ollama, the runner checks that the named model is installed and records its
digest; resume refuses a changed digest under the same model name.
Before a full run, make a short pilot outside the final 15 policies; do not tune
prompts using final-test outcomes. `--policy-ids P01` is useful for a technical
smoke test, but a result used to tune prompts should not then be counted as a
held-out final result. Use a new output directory after changing prompts.

An interrupted run can be resumed with the same options and output directory
plus `--resume`:

```sh
PYTHONPATH=. .venv/bin/python -m rq3.run --backend ollama --model qwen3.5:9b --out-dir rq3/results/main --resume
```

Every completed model call is saved atomically to `pending_job.json`; every
finished job is durably appended to `runs.jsonl`. Resume skips completed jobs
and completed calls within the interrupted job. A call interrupted while the
model is answering is run again. A torn final JSONL line is preserved as an
`.incomplete-*.bin` file and removed from the active journal. A transport failure
stops the runner after the failed job is saved; resume retries it and retains
each attempt in the journal. Malformed JSON
returned by the model is a terminal experimental result and is **not** retried,
so schema validity is not artificially improved. The scoring script uses the
last attempt of each job. A lock prevents two runners from using the same
output directory concurrently. Resume rejects changes to model settings,
manifest, prompts, runner and chunking code.

The companion `run_metadata.json` records model settings, chunk settings and
hashes of the manifest and experiment code.
The runner never modifies the main application extraction code.

## Saved output

Each `runs.jsonl` line is one policy/configuration/repeat job. It includes:

- policy ID, source path and SHA-256;
- configuration, repeat, model and backend;
- chunk offsets and digests;
- every model prompt, raw response, parsed response, parse status and token usage
  when available;
- start/end timestamps and elapsed seconds for each call and the full job;
- the unmodified final model response and job status.

No invalid JSON is repaired and no evidence is silently removed. The raw output
is kept so an independent scoring script can apply different scoring rules.

## Human reference and scoring

Two annotators should label all 15 policies independently using a shared field
guide, then record an adjudicated `gold.jsonl`. One line has this shape:

```json
{"policy_id":"P01","fields":{"dataTypeTags":["location"],"sharingCondition":"unclear"}}
```

The actual row must include all 20 fields. List fields contain arrays of labels
from `server/processor.py`; status fields are `yes`, `no` or `unclear`.
`unclear` combines missing and ambiguous disclosure because that is the current
application schema. If the research needs to distinguish those cases, extend
the annotation guide and output schema *before* final scoring. The generated
`annotation_template.jsonl` uses `null` placeholders and is not a gold set.

Run the separate scoring script after collecting outputs:

```sh
PYTHONPATH=. .venv/bin/python -m rq3.evaluate rq3/results/main/runs.jsonl --gold rq3/gold.jsonl
```

It writes `scores_by_run.csv` and `summary.csv`. Precision/recall/F1 count each
list label or explicit yes/no status as one asserted fact; `unclear` is an
abstention, not a positive fact. Gold `unclear` creates no positive fact.
The CLI requires all 225 jobs and no unresolved transport failures before
scoring with gold; `--allow-partial` is available for diagnostics. The
abstention rate is conditional on schema-valid outputs and is named accordingly
in the summary. Condition and negation rates compare the complete values of
tagged fields; they do not directly score preservation of linguistic scope.
Macro and paired policy-level comparisons should be added when writing the
research results; repeats are not independent policies.

The automatic `exact_quote_rate` checks whether at least one quotation for each
asserted fact appears verbatim in the source. **A matching quote does not prove
that the quote supports the claim.** To score semantic evidence validity and
unsupported assertions, complete the generated
`manual_review_template.jsonl` for every assertion and pass it as `--review`.
`evidence_valid` judges whether a quoted passage actually supports the value;
`assertion_supported` judges whether the claim is supported anywhere in the
policy. The evaluator rejects incomplete review coverage. For condition and
negation accuracy, annotators mark relevant field names in each gold row's
`condition_fields` and `negation_fields`. The evaluator compares the full field
value, including abstentions and invalid JSON. A category with no tagged cases
has a blank rate.

```sh
PYTHONPATH=. .venv/bin/python -m rq3.evaluate rq3/results/main/runs.jsonl --gold rq3/gold.jsonl --review rq3/review.jsonl
```

The final report still needs inter-annotator agreement before adjudication,
paired uncertainty intervals across the 15 policies, prompt and model version
reporting, and a coded qualitative error analysis. A small, short-policy sample
supports an exploratory comparison; it does not establish general performance
on long policies. Three repeats at temperature zero may be nearly identical;
retain the repeats as a stability check rather than treating them as new data.
