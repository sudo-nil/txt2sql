"""Vertex AI Gemini client via google-genai SDK."""

import os

from dotenv import load_dotenv
from google import genai

load_dotenv()

DEFAULT_MODEL = "gemini-2.5-pro"


def get_client() -> genai.Client:
    return genai.Client(
        vertexai=True,
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
    )


def generate(client: genai.Client, prompt: str) -> str:
    model = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
    response = client.models.generate_content(model=model, contents=prompt)
    return response.text


def ping(client: genai.Client) -> str:
    reply = generate(client, "Reply with exactly: GEMINI OK")
    return f"Gemini ping OK: {reply.strip()}"
