# P1 Privacy Policy Risk Classifier

P1 classifies a privacy policy as `High-Risk` or `Not High-Risk` using the
OpenAI API. The Base Mainnet compliance pipeline runs P1 before P2 and P3.

## Configuration

From the repository root, install the dependencies:

```bash
pip install -r requirements.txt
```

The Base Mainnet launcher reads `OPENAI_API_KEY` from
`config/base-mainnet.env` and passes it to P1, P2, and P3. For a standalone P1
run, set `OPENAI_API_KEY` in the environment first.

The default model is `gpt-4o-mini`, matching P2 and P3. Override it with
`--model` or, for the complete listener pipeline, `COMPLIANCE_GPT_MODEL`.

## High-risk classification

```bash
python high_risk_detection.py \
  --in_dir ./origin_pp \
  --out_dir ./risk_result \
  --model gpt-4o-mini
```

Each input creates `<stem>.json` containing:

- `classification`: `High-Risk` or `Not High-Risk`
- `analysis`: the model's reasoning and direct policy evidence
- `model` and `policy_file`: audit metadata

In the complete P1/P2/P3 pipeline, P1 runs first. Its classification selects the
P3 checklist when `--high-risk auto` is used. `--high-risk yes` and
`--high-risk no` remain available as explicit overrides.

## Key files

- `src/clients/gpt_api.py`: shared P1 OpenAI call and retry handling
- `src/prompts/risk_prompt.py`: high-risk classification prompt
- `src/analyzers/high_risk_analyser.py`: prompt-to-client adapter
