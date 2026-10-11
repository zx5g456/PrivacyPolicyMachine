# RQ3 human annotation guide (draft for annotator training)

## Unit and output

Annotate each whole policy in `policies.csv`, not individual chunks. Work from
the frozen local source file identified by the manifest SHA-256. Annotators A
and B work independently and do not see model outputs or each other's labels.
For each policy, label all 20 fields in a separate JSONL file. Record a short
source quote and a note for disputed or conditional cases in an annotation log;
the scoring JSONL contains only the final field values.

## General rules

- Use only explicit statements in the policy. Do not infer from the app type,
  jurisdiction, website domain, or common industry practice.
- For list fields, select every allowed label clearly supported by the policy.
  Use an empty list when none is supported. A field can contain multiple labels.
- For status fields, use `yes` for an explicit positive statement and `no` for
  an explicit negative statement about that field. Use `unclear` when the topic
  is absent, ambiguous, or cannot be resolved. Do not turn silence into `no`.
- Preserve the scope of a statement. “We may share with service providers” is
  a conditional statement, not a categorical promise that all data is shared.
- Quoted evidence should contain the relevant sentence and, when necessary,
  the adjacent condition or exception. A topic heading alone is not evidence.
- In the gold JSONL, list fields whose interpretation depends on a condition in
  `condition_fields`, and fields whose interpretation depends on a negation in
  `negation_fields`. Mark the field even when the correct value is empty or
  `unclear`, so omitted model findings count as errors on these cases.
- If two passages genuinely conflict, record both in the log and use `unclear`
  for that status until adjudication. Do not prefer the latest-looking passage
  without a documented reason.
- Use the policy text as collected. Do not correct spelling or normalize quotes
  in the source. Ignore unrelated navigation, cookie banners and terms of
  service if they do not state the app's privacy practice.

## Field scope

The allowed labels for the nine list fields are fixed in `server/processor.py`:
`dataTypeTags`, `dataSourceTypes`, `collectionContext`, `processingPurpose`,
`permittedUsage`, `thirdPartySources`, `downstreamStakeholders`,
`thirdPartyPurpose`, and `regulatoryFramework`. Mark a label only when its
specific meaning is supported. For example, mentioning Google in a contact
address is not evidence of `google_login`; naming GDPR in a generic link is not
evidence that the policy states GDPR as an applicable framework.

| Status field | Question to answer |
| --- | --- |
| `sharingCondition` | Does the policy state a condition or limit governing third-party sharing? |
| `consentRequired` | Does it say consent is required for a stated processing activity? |
| `optOutAvailable` | Does it provide an opt-out or withdrawal option? |
| `deletionAvailable` | Can the user request or perform deletion of their data? |
| `requestChannel` | Is a channel given for privacy or data-rights requests? |
| `retentionPolicy` | Is a retention or deletion rule stated? A numeric period is not required. |
| `encryptionApplied` | Does it state that data is encrypted? |
| `anonymisation` | Does it state that data is anonymised or de-identified? |
| `crossBorderTransfer` | Does it state that data is transferred across borders? |
| `childDataInvolved` | Does it state that children's data is collected or processed? |
| `contactChannel` | Is a privacy-related contact email, form, phone or address provided? |

`requestChannel` concerns making a rights request; `contactChannel` is any
privacy-related contact route. The two may be supported by the same passage.
For `sharingCondition`, an explicit “we do not share” statement is `no`; a
condition such as “only with your consent” is `yes`; silence is `unclear`.
For `childDataInvolved`, “not intended for children” alone does not prove
non-collection; use `no` only when the text explicitly denies collecting or
processing children's data. Cases that remain ambiguous go to adjudication.

## Adjudication and record keeping

1. Train both annotators on a small pilot outside the final 15 policies and
   revise this guide before scoring the final set.
2. Save independent A and B JSONL files unchanged. Calculate field-level
   agreement before discussion, separately for list labels and status fields.
3. Discuss disagreements using source quotations. Record the final choice and
   rationale. Use a third adjudicator if discussion cannot resolve a case.
4. Export one complete `gold.jsonl` using the schema in `rq3/README.md`.
   Freeze it before inspecting C0–C4 aggregate scores.

This guide is a draft. Any scope change made during the pilot must be applied
consistently to all 15 final policies and documented with a versioned guide.
