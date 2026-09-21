from config import GPT_MODEL
from src.prompts.data_type_prompt import construct_data_type_prompt
from src.clients.gpt_api import get_gpt_response


def analyze_data_types(policy_text, filename, model=GPT_MODEL):
    """
    Analyze the XR privacy policy text for data types.
    """
    prompt = construct_data_type_prompt(policy_text, filename)
    response = get_gpt_response(prompt, filename, model=model)
    return response
