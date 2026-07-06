"""LLM client: Vertex AI Gemini via langchain-google-genai."""

import os

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()

DEFAULT_MODEL = "gemini-2.5-flash"


def get_llm() -> ChatGoogleGenerativeAI:
    # GOOGLE_GENAI_USE_VERTEXAI=true routes to Vertex AI using ADC.
    # Project and location are read from GOOGLE_CLOUD_PROJECT / GOOGLE_CLOUD_LOCATION.
    return ChatGoogleGenerativeAI(
        model=os.environ.get("GEMINI_MODEL", DEFAULT_MODEL),
    )


def generate(model: ChatGoogleGenerativeAI, prompt: str) -> str:
    response = model.invoke([HumanMessage(content=prompt)])
    return response.content


def ping(model: ChatGoogleGenerativeAI) -> str:
    reply = generate(model, "Reply with exactly: GEMINI OK")
    return f"Gemini ping OK: {reply.strip()}"
