# information_extract.py
# ----------------------
# Function: Extract 8 categories of information from VR/AR application privacy policy texts
# using a "keyword recall + GPT extraction" method.
# Performs only "information extraction"—does not make Yes/No/Unknown judgments.
#
# Example run:
#   export OPENAI_API_KEY=sk-xxx
#   python3 information_extract.py --in_dir "../benchmark_20/high_risk/" --out_dir "./extraction_results"


import re
import json
import argparse
from typing import List, Dict, Any
from collections import defaultdict
from openai import OpenAI

KEYWORDS = {
    "data_types_collected": [
        "personal data", "personal information", "data we collect", "information we collect",
        "biometric", "voiceprint", "facial recognition", "iris scan", "gaze tracking", "eye tracking",
        "location data", "geolocation", "IP address", "contact information", "email address",
        "payment information", "health data", "physiological data", "behavioral data",
        "usage data", "device information", "sensor data"
    ],
    "data_sources": [
        "data sources", "information obtained from", "collected from", "gathered from",
        "provided by user", "from your device", "device sensors", "third-party", "third party",
        "publicly available sources", "partner", "vendor", "service provider"
    ],
    "purposes_of_use": [
        "use of data", "how we use", "purpose", "for the purpose of", "in order to",
        "used to provide", "used to improve", "used for marketing", "used for analytics",
        "used for personalisation", "used for personalization", "used for research",
        "used for safety", "used for training", "profiling", "automated decision-making",
        "automated decision making"
    ],
    "legal_basis": [
        "legal basis", "lawful basis", "under GDPR", "consent", "contract",
        "legal obligation", "legitimate interest", "vital interest", "public interest"
    ],
    "automated_decision_making": [
        "automated decision", "automated processing", "profiling", "algorithmic decision",
        "without human intervention", "AI-based decision", "automated evaluation"
    ],
    "user_rights": [
        "user rights", "your rights", "right to access", "right to correction",
        "right to rectification", "right to deletion", "right to erasure",
        "right to be forgotten", "right to object", "right to restriction",
        "data portability", "right to withdraw consent"
    ],
    "retention_deletion_policy": [
        "data retention", "how long we keep", "retain your data", "storage period",
        "deletion policy", "data deletion", "remove your data", "erase your data",
        "right to be forgotten"
    ],
    "contact_dpo_info": [
        "contact us", "contact information", "data protection officer", "DPO",
        "email us at", "address", "privacy contact"
    ]
}

CAT_PRETTY_NAME = {
    "data_types_collected": "Data types collected",
    "data_sources": "Data sources",
    "purposes_of_use": "Purposes of use",
    "legal_basis": "Legal basis",
    "automated_decision_making": "Automated decision-making",
    "user_rights": "User rights",
    "retention_deletion_policy": "Retention/deletion policy",
    "contact_dpo_info": "Contact/DPO info"
}




_SENT_SPLIT = re.compile(r'(?<=[\.\!\?；。！？])\s+|\n+')

def sentence_tokenize(text: str) -> List[str]:
    # 简单英文句子分割（兼容少量中式标点&换行）
    sents = [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]
    return sents

def harvest_candidates(text: str,
                       keywords: Dict[str, List[str]],
                       window: int = 1,
                       max_per_cat: int = 60) -> Dict[str, List[str]]:
    """
    关键词召回候选句子，带上下文窗口，去重合并。
    window=1 表示把命中句的前后各1句作为上下文。
    """
    sents = sentence_tokenize(text)
    lower_sents = [s.lower() for s in sents]
    out = defaultdict(list)

    for cat, kws in keywords.items():
        hit_idxs = set()
        for i, s in enumerate(lower_sents):
            for kw in kws:
                if re.search(r'\b' + re.escape(kw.lower()) + r'\b', s):
                    hit_idxs.update(range(max(0, i - window), min(len(sents), i + window + 1)))
                    break
        # 合并为段落块（把连续的句子连接为一段）
        blocks, cur = [], []
        for idx in sorted(hit_idxs):
            if not cur or idx == cur[-1] + 1:
                cur.append(idx)
            else:
                blocks.append(" ".join(sents[j] for j in cur))
                cur = [idx]
        if cur:
            blocks.append(" ".join(sents[j] for j in cur))

        # 去重、限量
        seen = set()
        cleaned = []
        for b in blocks:
            bb = b.strip()
            if bb and bb not in seen:
                seen.add(bb)
                cleaned.append(bb)
            if len(cleaned) >= max_per_cat:
                break

        out[cat] = cleaned
    return out

EMAIL_RE = re.compile(r'[\w\.-]+@[\w\.-]+\.\w+')
PHONE_RE = re.compile(r'(?:(?:\+\d{1,3}\s*)?(?:\(?\d{2,4}\)?[\s.-]*)?\d{3,4}[\s.-]?\d{3,4})')
ADDRESS_HINT_RE = re.compile(r'\b(street|road|rd\.?|avenue|ave\.?|suite|floor|level|boulevard|blvd\.?|way|lane|ln\.?|postcode|zip|city|state|country)\b', re.I)

def contact_regex_hints(text: str) -> Dict[str, List[str]]:
    emails = list(set(EMAIL_RE.findall(text)))
    phones = list(set(PHONE_RE.findall(text)))
    # 抓取包含地址关键词的句子作为“地址片段线索”
    addr_snips = []
    for s in sentence_tokenize(text):
        if ADDRESS_HINT_RE.search(s):
            addr_snips.append(s.strip())
    return {"emails": emails, "phones": phones, "address_snippets": addr_snips[:20]}

SYSTEM_PROMPT = """You are an expert information extractor for privacy policies of VR/AR applications.
You MUST extract ONLY from the provided snippets. If something is not present in the snippets, return empty lists/fields.
Summarize concisely; keep wording faithful to the policy (no speculation)."""

USER_PROMPT_TEMPLATE = """Extract structured information for the categories below from the provided snippets.
Only use the given snippets per category; DO NOT infer from outside knowledge.

Return STRICT JSON object matching this schema:

{{
  "data_types_collected": [{{"type": "string", "examples": ["string", "..."], "quotes": ["string", "..."]}}],
  "data_sources":          [{{"source": "string", "quotes": ["string", "..."]}}],
  "purposes_of_use":       [{{"purpose": "string", "quotes": ["string", "..."]}}],
  "legal_basis":           [{{"basis": "consent|contract|legal_obligation|legitimate_interest|vital_interest|public_interest|other", "detail": "string", "quotes": ["string"]}}],
  "automated_decision_making": {{"mentions": true/false, "details": "string", "quotes": ["string"]}},
  "user_rights":           [{{"right": "string", "quotes": ["string"]}}],
  "retention_deletion_policy": [{{"rule": "string", "duration": "string", "quotes": ["string"]}}],
  "contact_dpo_info":      {{"emails": ["string"], "phones": ["string"], "dpo_names": ["string"], "address_snippets": ["string"], "quotes": ["string"]}}
}}

Category snippets (empty means none were found by keywords):

{snippets_block}

If snippets are empty for a category, leave the corresponding list empty (or set mentions=false) without guessing.
When adding "quotes", include short verbatim fragments from the snippets that directly support the extracted item.
Be concise and avoid duplication.
"""

def llm_extract(snippets_by_cat: Dict[str, List[str]],
                contact_hints: Dict[str, List[str]],
                model: str = "gpt-4o-mini") -> Dict[str, Any]:
    client = OpenAI()

    # 把候选片段打包成一个用户消息
    lines = []
    for key, pretty in CAT_PRETTY_NAME.items():
        parts = snippets_by_cat.get(key, [])
        if parts:
            joined = "\n- " + "\n- ".join(parts[:80])
        else:
            joined = " (no snippets)"
        lines.append(f"### {pretty}\n{joined}\n")
    # 传入正则找到的 email/phone/address 作为辅助线索（供 contact 抽取参考）
    if contact_hints.get("emails") or contact_hints.get("phones") or contact_hints.get("address_snippets"):
        lines.append("### Regex contact hints\n- emails: " + ", ".join(contact_hints.get("emails", [])))
        lines.append("- phones: " + ", ".join(contact_hints.get("phones", [])))
        if contact_hints.get("address_snippets"):
            lines.append("- address_snippets:\n  - " + "\n  - ".join(contact_hints["address_snippets"][:10]))

    user_prompt = USER_PROMPT_TEMPLATE.format(snippets_block="\n".join(lines))

    # 要求模型给 JSON；如果你的 openai 版本支持，可以加 response_format={"type": "json_object"}
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
        # 简单兜底：去除 json 之外的字符再解析
        m = re.search(r"\{.*\}", content, re.S)
        return json.loads(m.group(0)) if m else {"error": "Model did not return JSON", "raw": content}

# ========== 5) 主流程 ==========
def extract_policy_info(policy_text: str,
                        model: str = "gpt-4o-mini",
                        window: int = 1) -> Dict[str, Any]:
    # 关键词召回
    snippets = harvest_candidates(policy_text, KEYWORDS, window=window)

    # 联系方式正则补强（供 contact 类别参考）
    contact_hints = contact_regex_hints(policy_text)

    # LLM 结构化抽取
    llm_result = llm_extract(snippets, contact_hints, model=model)

    # 附加：把召回到的片段也一并返回，便于审计
    return {
        "extraction": llm_result,
        "evidence_snippets": {CAT_PRETTY_NAME[k]: v for k, v in snippets.items()},
        "regex_contact_hints": contact_hints,
        "model": model
    }

# # ========== 6) CLI ==========
# if __name__ == "__main__":
#     parser = argparse.ArgumentParser()
#     parser.add_argument("--in", dest="inp", required=True, help="Path to privacy policy .txt")
#     parser.add_argument("--out", dest="outp", required=True, help="Path to output JSON")
#     parser.add_argument("--model", default="gpt-4o-mini", help="OpenAI model, e.g., gpt-4o-mini / gpt-4o / gpt-5.1-mini")
#     parser.add_argument("--window", type=int, default=1, help="context window (sentences) around keyword hits")
#     args = parser.parse_args()

#     with open(args.inp, "r", encoding="utf-8", errors="ignore") as f:
#         text = f.read()

#     result = extract_policy_info(text, model=args.model, window=args.window)

#     with open(args.outp, "w", encoding="utf-8") as f:
#         json.dump(result, f, ensure_ascii=False, indent=2)

#     print(f"[OK] Saved extraction JSON to: {args.outp}")

# ========== 6) CLI (folder version) ==========
if __name__ == "__main__":
    from pathlib import Path
    import json

    parser = argparse.ArgumentParser()
    parser.add_argument("--in_dir", required=True, help="Directory containing privacy policy .txt files")
    parser.add_argument("--out_dir", required=True, help="Directory to write output JSON files")
    parser.add_argument("--model", default="gpt-4o-mini", help="OpenAI model, e.g., gpt-4o-mini / gpt-4o / gpt-5.1-mini")
    parser.add_argument("--window", type=int, default=1, help="context window (sentences) around keyword hits")
    args = parser.parse_args()

    in_dir = Path(args.in_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 仅遍历 in_dir 下的一层 .txt 文件（非递归）
    txt_files = sorted([p for p in in_dir.iterdir() if p.is_file() and p.suffix.lower() == ".txt"])

    if not txt_files:
        print(f"[WARN] No .txt files found in: {in_dir}")

    for pp_path in txt_files:
        try:
            with pp_path.open("r", encoding="utf-8", errors="ignore") as f:
                policy_text = f.read()

            result = extract_policy_info(policy_text, model=args.model, window=args.window)

            out_path = out_dir / f"{pp_path.stem}.json"
            with out_path.open("w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            print(f"[OK] Saved: {out_path}")
        except Exception as e:
            print(f"[ERROR] {pp_path.name}: {e}")
