"""Explain authoritative engine results using Azure OpenAI and Entra identity."""
import json
import os
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field, ValidationError


class AIUnavailable(Exception):
    """A safe, user-facing AI service failure."""


INSTRUCTIONS = """Explain the supplied mortgage engine results in plain British English.
Treat the supplied figures and milestone findings as authoritative. Do not recalculate,
invent figures, rates, lender products or eligibility, or change any milestone finding.
Explain only the tested options, cash remaining and trade-offs. A lower mortgage balance
includes the user's overpayment: do not describe the entire reduction as interest saved.
Use brief plain-text paragraphs, no Markdown. Do not recommend a particular option.
State that overpayments happen now, monthly payments and interest rate stay unchanged,
and property value stays constant. Mention that fees, overpayment penalties, emergency
savings needs and savings interest are not modelled. End by noting that this is an
AI-generated explanation for planning, not regulated financial advice. Keep under 250 words.
"""


class Content(BaseModel):
    type: str
    text: str = ""


class Output(BaseModel):
    type: str
    content: list[Content] = Field(default_factory=list)


class Response(BaseModel):
    status: str
    output: list[Output]


def _access_token() -> str:
    # Lazy import: ordinary calculations still work without AI dependencies/config.
    try:
        from azure.identity import DefaultAzureCredential, ManagedIdentityCredential

        client_id = os.getenv("AZURE_CLIENT_ID")
        credential = (
            ManagedIdentityCredential(client_id=client_id)
            if os.getenv("IDENTITY_ENDPOINT")
            else DefaultAzureCredential(managed_identity_client_id=client_id)
        )
        with credential:
            return credential.get_token("https://cognitiveservices.azure.com/.default").token
    except Exception:
        raise AIUnavailable("AI authentication is unavailable. Calculated results are still available.") from None


def explain_results(inputs: dict, results: dict) -> str:
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip().rstrip("/")
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "").strip()
    parsed = urlsplit(endpoint)
    if (not deployment or parsed.scheme != "https" or not parsed.hostname
            or parsed.path not in ("", "/openai/v1", "/openai/v1/responses") or parsed.query
            or parsed.fragment or parsed.username or parsed.password):
        raise AIUnavailable("AI explanations are not configured. Calculated results are still available.")
    url = "https://" + parsed.netloc + "/openai/v1/responses"
    token = _access_token()
    try:
        with httpx.Client(timeout=httpx.Timeout(40, connect=5)) as client:
            response = client.post(
                url,
                headers={"Authorization": "Bearer " + token},
                json={
                    "model": deployment,
                    "instructions": INSTRUCTIONS,
                    "input": json.dumps({"mortgage_inputs": inputs, "engine_results": results}),
                    "max_output_tokens": 2000,
                    "store": False,
                },
            )
            response.raise_for_status()
            result = Response.model_validate(response.json())
        text = "\n\n".join(
            content.text.strip()
            for item in result.output if item.type == "message"
            for content in item.content if content.type == "output_text" and content.text.strip()
        )
        if result.status != "completed" or not text or len(text) > 12000:
            raise AIUnavailable("AI could not complete an explanation. Please try again.")
        return text
    except (httpx.HTTPError, ValueError, ValidationError):
        # Never expose provider responses, tokens or financial inputs in errors/logs.
        raise AIUnavailable("AI explanations are temporarily unavailable. Please try again; your calculated results are unchanged.") from None
