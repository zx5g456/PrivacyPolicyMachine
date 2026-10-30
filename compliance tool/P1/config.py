"""Configuration for the P1 high-risk classifier."""

GPT_MODEL = "gpt-4o-mini"
GPT_MAX_TOKENS = 3000
GPT_TEMPERATURE = 0.1
BASE_DELAY = 1
MAX_RETRIES = 3

ROOT_DIRECTORY = "./origin_pp"
RISK_RESULT_DIRECTORY = "./risk_result"
SUPPORTED_EXTENSIONS = [".txt", ".md", ".html"]
