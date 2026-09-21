from __future__ import annotations

import importlib.util
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace


TOOL_ROOT = Path(__file__).resolve().parents[1]
P1_ROOT = TOOL_ROOT / "P1"
sys.path.insert(0, str(TOOL_ROOT))
sys.path.insert(0, str(P1_ROOT))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


p1 = load_module("p1_high_risk_detection", P1_ROOT / "high_risk_detection.py")
pipeline = load_module("compliance_pipeline", TOOL_ROOT / "run_compliance.py")
from src.clients import gpt_api
from src.prompts.data_type_prompt import construct_data_type_prompt
from src.prompts.risk_prompt import construct_risk_prompt


def test_extract_risk_classification():
    assert (
        p1.extract_risk_classification(
            "High-Risk Classification: [High-Risk]\nReasoning: explicit use"
        )
        == "High-Risk"
    )
    assert (
        p1.extract_risk_classification(
            "High-Risk Classification: Not High-Risk\nReasoning: no match"
        )
        == "Not High-Risk"
    )


def test_key_p1_prompts_are_preserved():
    risk_prompt = construct_risk_prompt("policy body", "policy.txt")
    assert "High-Risk Determination Logic" in risk_prompt
    assert "EU AI Act Annex III" in risk_prompt
    assert "Always quote directly from the privacy policy" in risk_prompt
    assert "High-Risk Classification" in risk_prompt

    data_type_prompt = construct_data_type_prompt("policy body", "policy.txt")
    assert "XR_TYPE_CHECKLIST" in data_type_prompt
    assert "Be conservative" in data_type_prompt


def test_p1_writes_structured_result(monkeypatch, tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    (input_dir / "policy.txt").write_text("sample policy", encoding="utf-8")

    monkeypatch.setattr(
        p1,
        "analyze_risk",
        lambda policy_text, filename, model: (
            "High-Risk Classification: Not High-Risk\n"
            "Reasoning: no high-risk purpose.\nEvidence: none."
        ),
    )

    p1.detect_high_risk(input_dir, output_dir, "gpt-test")

    result = json.loads((output_dir / "policy.json").read_text(encoding="utf-8"))
    assert result["classification"] == "Not High-Risk"
    assert result["model"] == "gpt-test"


def test_p1_client_calls_public_gpt_api(monkeypatch):
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        message = SimpleNamespace(content="model result")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    monkeypatch.setattr(gpt_api, "OpenAI", lambda: fake_client)

    result = gpt_api.get_gpt_response("important P1 prompt", "policy.txt", "gpt-test")

    assert result == "model result"
    assert captured["model"] == "gpt-test"
    assert captured["messages"] == [
        {"role": "user", "content": "important P1 prompt"}
    ]


def test_pipeline_uses_p1_classification_for_p3(monkeypatch, tmp_path):
    p3_modes = []

    def fake_run_stage(label, command, environment):
        output_dir = Path(command[command.index("--out_dir") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        if label.startswith("P1"):
            (output_dir / "policy.json").write_text(
                json.dumps({"classification": "Not High-Risk"}),
                encoding="utf-8",
            )
        elif label.startswith("P2"):
            (output_dir / "policy.json").write_text("{}", encoding="utf-8")
        else:
            p3_modes.append(command[command.index("--high_risk") + 1])
            (output_dir / "policy.json").write_text("{}", encoding="utf-8")
            (output_dir / "policy.md").write_text("result", encoding="utf-8")

    monkeypatch.setattr(pipeline, "load_gpt_api_key", lambda: "test-key")
    monkeypatch.setattr(pipeline, "run_stage", fake_run_stage)

    output_dir = tmp_path / "results"
    pipeline.run_compliance(
        b"policy",
        output_dir,
        "gpt-test",
        "auto",
        "0x" + "11" * 32,
        "0x" + hashlib.sha256(b"policy").hexdigest(),
    )

    assert p3_modes == ["no"]
    assert (output_dir / "p1-risk.json").is_file()
    assert (output_dir / "p2-extraction.json").is_file()
    assert (output_dir / "p3-checklist.json").is_file()
    assert (output_dir / "p3-checklist.md").is_file()
    assert (output_dir / "compliance-bundle.zip").is_file()
    assert (output_dir / "compliance-manifest.json").is_file()
