"""Send one captured JPEG and a question to the Anthropic Claude API."""
import base64
import os
import time
from pathlib import Path
from dotenv import dotenv_values
from anthropic import Anthropic, APIConnectionError, APITimeoutError, APIStatusError

DEFAULT_PROMPT = (
    "Describe what is visible in this photo. Identify the main objects and any "
    "clearly visible activity. Be concise and state uncertainty instead of guessing."
)


class AnalysisError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


def analyze_photo(jpeg, prompt, *, output_schema=None):
    settings = {**dotenv_values(Path(__file__).resolve().parents[2] / ".env"), **os.environ}
    key = (settings.get("ANTHROPIC_API_KEY") or "").strip()
    model = (settings.get("ANTHROPIC_MODEL", "claude-sonnet-5-5") or "").strip()
    if not key:
        raise AnalysisError("Add ANTHROPIC_API_KEY to the project .env, then click Analyze again.", 503)
    if not model:
        raise AnalysisError("Set ANTHROPIC_MODEL in .env, then click Analyze again.", 503)
    prompt = prompt.strip() or DEFAULT_PROMPT
    image_data = base64.b64encode(jpeg).decode("ascii")
    output_options = {} if output_schema is None else {"output_config": {"format": {"type": "json_schema", "schema": output_schema}}}
    started = time.monotonic()
    try:
        with Anthropic(api_key=key, base_url="https://api.anthropic.com", timeout=120, max_retries=0) as client:
            response = client.messages.create(
                model=model,
                max_tokens=1024,
                **output_options,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_data}},
                    {"type": "text", "text": prompt},
                ]}],
            )
    except APITimeoutError:
        raise AnalysisError("The model timed out. Try again.", 504) from None
    except APIConnectionError:
        raise AnalysisError("Cannot reach the model API. Check the endpoint and network.", 502) from None
    except APIStatusError as error:
        messages = {
            401: "The API key was rejected. Check it locally in .env and try again.",
            403: "This account cannot access the model. Check model access in your provider account.",
            404: "Model or endpoint not found. Check ANTHROPIC_MODEL.",
            429: "API quota or rate limit reached. Check your account or try again later.",
        }
        raise AnalysisError(messages.get(error.status_code, "The model API rejected the request. Check image/model compatibility and try again."), 502) from None
    except Exception:
        # Never return provider exceptions: they may contain request data or credentials.
        raise AnalysisError("The analysis request failed. Check your model configuration and try again.", 502) from None
    if response.stop_reason != "end_turn":
        raise AnalysisError("The model did not complete its answer. Try again.")
    answer = "\n".join(block.text for block in response.content if block.type == "text").strip()
    if not answer:
        raise AnalysisError("The model returned no text. Try another question or photo.")
    return {"answer": answer, "model": model, "prompt": prompt,
            "elapsed_seconds": round(time.monotonic() - started, 2)}



