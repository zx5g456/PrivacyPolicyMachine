# evaluate_checklist.py
# ---------------------
# Usage：
#   export OPENAI_API_KEY=sk-xxx
#   python3 evaluate_checklist.py --report report.json --policy privacy.bighealth.com.txt --out compliance_results

# python3 evaluate_checklist.py \
#   --report_dir "../P2/extraction_results/high" \
#   --policy_dir "../benchmark_20/high_risk" \
#   --out_dir "./checklist_results_high" \
#   --high_risk yes

  # python3 evaluate_checklist.py \
  # --report_dir "../P2/extraction_results/low" \
  # --policy_dir "../benchmark_20/not_high_risk" \
  # --out_dir "./checklist_results_low" \
  # --high_risk no

#
# generate：
#   compliance_results.json
#   compliance_results.md

import os
import re
import json
import argparse
from pathlib import Path
from typing import Dict, Any, List
from openai import OpenAI
import unicodedata
DASH_RE = re.compile(r"[‐-‒–—−-]+")

def _slug(s: str) -> str:
    """Deterministic normalization for filename stems, no fuzzy."""
    s = unicodedata.normalize("NFKC", s).lower().strip()
    s = DASH_RE.sub("-", s)             # unify all dash variants to "-"
    s = re.sub(r"\s+", " ", s)          # collapse spaces
    # remove common boilerplate to stabilize naming; keep it deterministic
    s = s.replace("privacy policy", "").strip()
    # keep only letters/digits/space/hyphen
    s = re.sub(r"[^a-z0-9\- ]", "", s)
    return s


CHECKLIST_TEXT_HIGH = """Checklist to evaluate (answer only Yes or No for each item, no Unknown in this stage):
1. Data Types and Sources
1.1 Are all data types collected clearly listed (e.g., biometric, audio, behavioral)?
1.2 Are the data sources explained (user-provided, device sensors, third parties)?
1.3 Are sensitive data (e.g., biometric) distinguished from regular data?
1.4 Does the policy commit to data minimisation (collecting only what is necessary)?
1.5 Does the policy mention anonymisation or de-identification where possible?

2. Purpose Specification and Alignment
2.1 Are data usage purposes stated clearly and specifically?
2.2 If used for automated decision-making, is this explicitly stated?
2.3 Does the policy allow users to request an explanation for automated decisions?

3. Legal Basis and Justification
3.1 Is the legal basis for data processing provided (e.g., consent, contract)?
3.2 Does the policy explicitly state compliance with relevant laws/regulations (e.g., GDPR, CCPA, AI Act)?

4. User Transparency and Control
4.1 Are users informed how their data is used in the AI system?
4.2 Are user rights (access, correction, deletion, objection) explained?
4.3 Can users opt out of fully automated decisions?
4.4 Does the policy commit to keeping user data accurate and up-to-date?

5. Data Retention and Deletion
5.1 Is the data retention period or policy clearly stated?
5.2 Are users informed of their “Right to be Forgotten” and how to request deletion?

6. Risk Disclosure and Accountability
6.1 Is a contact point (e.g., Data Protection Officer) provided?
6.2 Does the policy identify the organisation(s) responsible for data processing (Data Controller/Processor)?
6.3 Does the policy describe a complaint or redress mechanism (e.g., filing with a regulator)?
6.4 If sensitive information is involved, does the policy confirm express consent was obtained and explain how consent can be withdrawn?
"""

CHECKLIST_TEXT_LOW = """Checklist to evaluate (answer only Yes or No for each item, no Unknown in this stage):
1. Data Types and Sources
1.1 Are all data types collected clearly listed (e.g., biometric, audio, behavioral)?
1.2 Are the data sources explained (user-provided, device sensors, third parties)?
1.3 Are sensitive data (e.g., biometric) distinguished from regular data?
1.4 Does the policy commit to data minimisation (collecting only what is necessary)?
1.5 Does the policy mention anonymisation or de-identification where possible?

2. Purpose Specification and Alignment
2.1 Are data usage purposes stated clearly and specifically?

3. Legal Basis and Justification
3.1 Is the legal basis for data processing provided (e.g., consent, contract)?
3.2 Does the policy explicitly state compliance with relevant laws/regulations (e.g., GDPR, CCPA, AI Act)?

4. User Transparency and Control
4.1 Are users informed how their data is used in the AI system?
4.2 Are user rights (access, correction, deletion, objection) explained?
4.4 Does the policy commit to keeping user data accurate and up-to-date?

5. Data Retention and Deletion
5.1 Is the data retention period or policy clearly stated?
5.2 Are users informed of their “Right to be Forgotten” and how to request deletion?

6. Risk Disclosure and Accountability
6.1 Is a contact point (e.g., Data Protection Officer) provided?
6.2 Does the policy identify the organisation(s) responsible for data processing (Data Controller/Processor)?
6.3 Does the policy describe a complaint or redress mechanism (e.g., filing with a regulator)?
6.4 If sensitive information is involved, does the policy confirm express consent was obtained and explain how consent can be withdrawn?
"""

# Orders for rendering & key list
ORDER_HIGH = [
    ("1.1","Are all data types collected clearly listed?"),
    ("1.2","Are the data sources explained?"),
    ("1.3","Are sensitive data distinguished?"),
    ("1.4","Commitment to data minimisation?"),
    ("1.5","Mentions anonymisation/de-identification?"),
    ("2.1","Purposes stated clearly and specifically?"),
    ("2.2","Automated decision-making explicitly stated?"),
    ("2.3","Users can request explanation for ADM?"),
    ("3.1","Legal basis provided?"),
    ("3.2","Explicitly states compliance (GDPR/CCPA/AI Act)?"),
    ("4.1","Users informed how data is used in AI?"),
    ("4.2","User rights explained?"),
    ("4.3","Users can opt out of fully automated decisions?"),
    ("4.4","Commitment to data accuracy & up-to-date?"),
    ("5.1","Retention period/policy stated?"),
    ("5.2","Right to be Forgotten & deletion request path?"),
    ("6.1","Contact point / DPO provided?"),
    ("6.2","Identifies Data Controller/Processor?"),
    ("6.3","Complaint/redress mechanism described?")
]

ORDER_LOW = [
    ("1.1","Are all data types collected clearly listed?"),
    ("1.2","Are the data sources explained?"),
    ("1.3","Are sensitive data distinguished?"),
    ("1.4","Commitment to data minimisation?"),
    ("1.5","Mentions anonymisation/de-identification?"),
    ("2.1","Purposes stated clearly and specifically?"),
    ("3.1","Legal basis provided?"),
    ("3.2","Explicitly states compliance (GDPR/CCPA/AI Act)?"),
    ("4.1","Users informed how data is used in AI?"),
    ("4.2","User rights explained?"),
    ("4.4","Commitment to data accuracy & up-to-date?"),
    ("5.1","Retention period/policy stated?"),
    ("5.2","Right to be Forgotten & deletion request path?"),
    ("6.1","Contact point / DPO provided?"),
    ("6.2","Identifies Data Controller/Processor?"),
    ("6.3","Complaint/redress mechanism described?"),
    ("6.4","Express consent for sensitive info & withdrawal path?")
]


# 要求严格 JSON 输出：每一条 -> {answer: "Yes"/"No", evidence: "...", rationale: "..."}
JSON_SCHEMA_EXAMPLE = {
    "1.1": {"answer": "Yes", "evidence": "short quote", "rationale": "why the evidence supports the answer"},
    "1.2": {"answer": "No",  "evidence": "",            "rationale": "no mention found in provided evidence"},
    # ...
}

SYSTEM_PROMPT = """You are a privacy compliance checker.
Use ONLY the provided evidence snippets and the given policy excerpt.
Be conservative: if the related text is not present, answer 'No'.
For each item return a short verbatim evidence quote (<= 30 words) when answering Yes.
Keep rationale concise (<= 40 words).
Return STRICT JSON where keys exactly match the checklist item IDs provided (e.g., '1.1', '1.2', ...). No extra commentary."""


def load_json(p: Path) -> Dict[str, Any]:
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

def load_text(p: Path, max_chars: int = 30000) -> str:
    with open(p, "r", encoding="utf-8", errors="ignore") as f:
        t = f.read()
    # 简单去掉多余空白并截断
    t = re.sub(r"[ \t]+\n", "\n", t)
    return t[:max_chars]

def collect_evidence_blocks(report: Dict[str, Any]) -> str:
    """
    从上一阶段的 report.json 里把各类抽取结果（含 quotes）拼成证据块。
    report 结构：
      {
        "extraction": {...},
        "evidence_snippets": {...},
        "regex_contact_hints": {...}
      }
    """
    ex = report.get("extraction", {})
    ev = report.get("evidence_snippets", {})
    hints = report.get("regex_contact_hints", {})

    lines: List[str] = []
    # 逐类拼接：优先使用 extraction 内的 quotes，其次是 evidence_snippets
    def add_section(title: str, payload: Any):
        lines.append(f"### {title}")
        if isinstance(payload, list):
            for item in payload[:50]:
                if isinstance(item, str):
                    lines.append(f"- {item}")
                elif isinstance(item, dict):
                    # 展平常见字段
                    for k, v in item.items():
                        if isinstance(v, list):
                            for vv in v[:5]:
                                lines.append(f"- {k}: {vv}")
                        else:
                            lines.append(f"- {k}: {v}")
        elif isinstance(payload, dict):
            for k, v in payload.items():
                if isinstance(v, list):
                    for vv in v[:10]:
                        lines.append(f"- {k}: {vv}")
                else:
                    lines.append(f"- {k}: {v}")
        else:
            lines.append(str(payload))

    # Data types
    add_section("Data types collected (extraction)", ex.get("data_types_collected", []))
    add_section("Data types collected (evidence)", ev.get("Data types collected", []))

    # Data sources
    add_section("Data sources (extraction)", ex.get("data_sources", []))
    add_section("Data sources (evidence)", ev.get("Data sources", []))

    # Purposes
    add_section("Purposes of use (extraction)", ex.get("purposes_of_use", []))
    add_section("Purposes of use (evidence)", ev.get("Purposes of use", []))

    # Legal basis
    add_section("Legal basis (extraction)", ex.get("legal_basis", []))
    add_section("Legal basis (evidence)", ev.get("Legal basis", []))

    # Automated decision-making
    add_section("Automated decision-making (extraction)", ex.get("automated_decision_making", {}))
    add_section("Automated decision-making (evidence)", ev.get("Automated decision-making", []))

    # User rights
    add_section("User rights (extraction)", ex.get("user_rights", []))
    add_section("User rights (evidence)", ev.get("User rights", []))

    # Retention/deletion
    add_section("Retention/deletion policy (extraction)", ex.get("retention_deletion_policy", []))
    add_section("Retention/deletion policy (evidence)", ev.get("Retention/deletion policy", []))

    # Contact/DPO
    add_section("Contact/DPO info (extraction)", ex.get("contact_dpo_info", {}))
    add_section("Contact/DPO info (evidence)", ev.get("Contact/DPO info", []))
    add_section("Regex contact hints", hints)

    return "\n".join(lines)[:35000]  # 再做一次整体截断

def call_model(evidence_block: str,
               policy_excerpt: str,
               keys: List[str],
               checklist_text: str,
               model: str = "gpt-4o-mini") -> Dict[str, Any]:
    client = OpenAI()

    # 动态示例 JSON（仅取前两个键做演示）
    schema_example = {}
    for k in keys[:2]:
        schema_example[k] = {"answer": "Yes", "evidence": "short quote", "rationale": "why the evidence supports the answer"}

    user_prompt = (
        f"{checklist_text}\n\n"
        f"Required JSON KEYS (must match exactly): {keys}\n\n"
        "=== Evidence snippets from prior information extraction ===\n"
        f"{evidence_block}\n\n"
        "=== Policy excerpt (verbatim) ===\n"
        f"{policy_excerpt}\n\n"
        "Return STRICT JSON like this shape (keys must match the list above):\n"
        f"{json.dumps(schema_example)}"
    )

    resp = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
    content = resp.choices[0].message.content
    try:
        return json.loads(content)
    except Exception:
        m = re.search(r"\{.*\}", content, re.S)
        if not m:
            raise RuntimeError("Model did not return JSON.")
        return json.loads(m.group(0))


def to_markdown(results: Dict[str, Any], order: List[tuple]) -> str:
    lines = ["# Compliance Checklist Results\n"]
    for key, q in order:
        item = results.get(key, {})
        ans = item.get("answer", "No")
        ev = item.get("evidence", "")
        rat = item.get("rationale", "")
        check = "☑️ Yes" if str(ans).lower().startswith("y") else "❌ No"
        lines.append(f"**{key} {q}** — {check}")
        if ev:
            lines.append(f"> Evidence: {ev}")
        if rat:
            lines.append(f"> Rationale: {rat}")
        lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report_dir", required=True, help="Directory containing report JSON files (from extraction step)")
    ap.add_argument("--policy_dir", required=True, help="Directory containing original policy .txt files")
    ap.add_argument("--out_dir", required=True, help="Directory to write checklist evaluation outputs")
    ap.add_argument("--high_risk", choices=["yes", "no"], default="yes", help="Use high-risk checklist ('yes') or low-risk checklist ('no')")
    ap.add_argument("--model", default="gpt-4o-mini")
    args = ap.parse_args()

    # 选择 checklist 文本与渲染顺序
    if args.high_risk == "yes":
        checklist_text = CHECKLIST_TEXT_HIGH
        order = ORDER_HIGH
    else:
        checklist_text = CHECKLIST_TEXT_LOW
        order = ORDER_LOW

    report_dir = Path(args.report_dir)
    policy_dir = Path(args.policy_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 索引 report.json -> 以“规范化 stem”为键，严格匹配（无模糊）
    report_files = [p for p in report_dir.iterdir() if p.is_file() and p.suffix.lower() == ".json"]
    report_slug_map = {}
    for rp in report_files:
        slug = _slug(rp.stem)
        if slug in report_slug_map:
            print(f"[WARN] Duplicate report slug '{slug}'. Keeping first: {report_slug_map[slug].name}")
            continue
        report_slug_map[slug] = rp

    # 以 policy(.txt) 为主遍历（权威命名）
    policy_files = sorted([p for p in policy_dir.iterdir() if p.is_file() and p.suffix.lower() == ".txt"])
    if not policy_files:
        print(f"[WARN] No .txt policies found in: {policy_dir}")

    keys = [k for k, _ in order]

    for pp in policy_files:
        stem = pp.stem
        slug = _slug(stem)
        rp = report_slug_map.get(slug)
        if rp is None:
            print(f"[SKIP] No matching report JSON for policy '{pp.name}' (slug='{slug}') in {report_dir}")
            continue

        try:
            report = load_json(rp)
            policy_excerpt = load_text(pp, max_chars=25000)
            evidence_block = collect_evidence_blocks(report)

            results = call_model(
                evidence_block=evidence_block,
                policy_excerpt=policy_excerpt,
                keys=keys,
                checklist_text=checklist_text,
                model=args.model
            )

            # 输出以“policy 文件名”为准
            out_json = out_dir / f"{stem}.json"
            with open(out_json, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)

            out_md = out_dir / f"{stem}.md"
            with open(out_md, "w", encoding="utf-8") as f:
                f.write(to_markdown(results, order=order))

            print(f"[OK] wrote {out_json} and {out_md}")
        except Exception as e:
            print(f"[ERROR] {stem}: {e}")


if __name__ == "__main__":
    main()
