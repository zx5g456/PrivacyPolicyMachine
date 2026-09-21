from config import GPT_MODEL
from src.prompts.risk_prompt import construct_risk_prompt
from src.clients.gpt_api import get_gpt_response


def analyze_risk(policy_text, filename, model=GPT_MODEL):
    """
    Analyze the XR privacy policy text for high-risk issues.
    """
    prompt = construct_risk_prompt(policy_text, filename)
    response = get_gpt_response(prompt, filename, model=model)
    return response
