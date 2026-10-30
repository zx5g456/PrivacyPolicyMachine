def construct_risk_prompt(policy_text, filename):
    prompt = f"""Role: You are a compliance auditor specializing in the EU AI Act. Your task is to determine whether a given VR/AR application, as described in its privacy policy, qualifies as a High-Risk AI System under the AI Act. You must be STRICT and PRECISE, relying only on explicit evidence from the text.

CRITICAL:
    * Do not infer or assume any data collection or usage beyond what is explicitly written.
    * Always quote directly from the privacy policy as evidence.

Input:
* Privacy policy text of the VR/AR application
* AIA High-Risk AI System categories and relevant XR-HSE use cases (see below)

High-Risk Determination Logic:

1. Purpose Check (Intended Use) Examine the privacy policy and identify if the application is explicitly used for any of the following High-Risk categories (EU AI Act Annex III):
    * Biometric Identification and Categorisation – facial recognition, iris scan, voiceprint, eye-tracking fatigue detection, physiological monitoring of workers.
    * Management of Critical Infrastructure – XR for safety-critical scheduling, emergency response training in energy, transport, or health sectors.
    * Education and Vocational Training – XR teaching/adaptive training, skill assessment, personalised guidance, professional certification.
    * Employment and Worker Management – behavioural monitoring, workload analytics, remote performance evaluation.
    * Access to Essential Services – XR systems determining eligibility for loans, benefits, healthcare, housing.
    * Law Enforcement – predictive policing, biometric surveillance, XR-based evidence analysis.
    * Migration, Asylum and Border Control – automated visa decision-making, biometric screening.
    * Administration of Justice and Democratic Processes – XR/AI for legal reasoning, court assistance, election integrity.

2. Check Data Collected Identify from the privacy policy whether the app explicitly collects any of the following sensitive or high-risk biometric/physiological data:
    * Biometric identifiers (facial data, iris scans, fingerprints, voiceprints)
    * Physiological signals (eye tracking, gaze data, heart rate, body temperature)
    * Behavioural data used for profiling or automated decision-making in high-risk contexts

3. High-Risk Classification Rules:
    * If purpose matches one of the high-risk categories → Mark as High-Risk, without sensitive data collection.
    * If data includes sensitive biometric/physiological signals AND the app uses them for high-risk purposes (identification, categorisation, safety-critical monitoring) → Mark as High-Risk.
    * If sensitive data is collected but purpose is low-risk → Mark as High-Risk and explain reasoning.
    * Otherwise → Mark as Not High-Risk.

Output Format:
High-Risk Classification: <High-Risk or Not High-Risk>
Reasoning: Summarise which purpose(s) and/or data types triggered the classification.
Evidence: Direct quotes from the privacy policy that support the classification.

Write exactly one classification line, using one of the two values above. Do not add
Markdown bullets, bold markers, brackets, or extra words to that line.

File being analyzed: {filename}

Privacy Policy Text to Analyze:
{'=' * 50}
{policy_text}
{'=' * 50}

Please provide your analysis following the exact output format specified above."""

    return prompt
