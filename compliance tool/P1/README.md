# P1 XR Privacy Policy Analyzer

P1 classifies an XR privacy policy as `High-Risk` or `Not High-Risk` using the
public OpenAI API. It keeps the original EU AI Act risk prompt and the optional
XR data-type prompt; AWS and Amazon Bedrock are not required.

## Configuration

Install the dependencies and provide an OpenAI API key:

```bash
pip install -r requirements.txt
export OPENAI_API_KEY="your_api_key"
```

When P1 is launched by `../run_compliance.py`, the shared configuration loader
uses `OPENAI_API_KEY` from the environment and passes it to P1, P2, and P3.
The Base Mainnet launcher loads that variable from `config/base-mainnet.env`.
Standalone legacy runs can still fall back to `../../data/gpt.zshrc` (or
`GPT_CONFIG_PATH`) when the environment variable is absent.

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

## Optional XR data-type analysis

```bash
python data_type_detection.py \
  --in_dir ./origin_pp \
  --out_dir ./datatype_result \
  --model gpt-4o-mini
```

This uses the original conservative XR data-type prompt and writes one
`<stem>_data_types.txt` result per policy.

## Key files

- `src/clients/gpt_api.py`: shared P1 OpenAI call and retry handling
- `src/prompts/risk_prompt.py`: original high-risk classification prompt
- `src/prompts/data_type_prompt.py`: original XR data-type prompt
- `src/analyzers/`: prompt-to-client adapters
