import argparse
import logging
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_groq import ChatGroq

if __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models import User
from schemas import ChatMessage, ChatRequest, ChatResponse
from security import get_current_user
from settings import settings

logger = logging.getLogger(__name__)
router = APIRouter()


def generate_chat_response(messages: list[ChatMessage]) -> str:
    if not settings.groq_api_key:
        raise HTTPException(
            status_code=503,
            detail="Chat is not configured. Set the GROQ_API_KEY environment variable.",
        )

    conversation = [
        SystemMessage(
            content="You are a helpful assistant in the Agent Workspace."
        ),
        *[
            HumanMessage(content=message.content)
            if message.role == "user"
            else AIMessage(content=message.content)
            for message in messages
        ],
    ]
    try:
        response = ChatGroq(
            model="openai/gpt-oss-20b",
            api_key=settings.groq_api_key,
        ).invoke(conversation)
    except Exception as exc:
        logger.exception("Chat provider request failed.")
        raise HTTPException(
            status_code=502,
            detail="The chat provider could not complete the request.",
        ) from exc

    if not isinstance(response.content, str) or not response.content.strip():
        logger.error("Chat provider returned an empty or unsupported response.")
        raise HTTPException(
            status_code=502,
            detail="The chat provider returned an invalid response.",
        )
    return response.content.strip()


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    _: User = Depends(get_current_user),
) -> ChatResponse:
    return ChatResponse(reply=generate_chat_response(payload.messages))


def run_cli_chat(prompt: str) -> str:
    """Run a single user prompt through the chat model."""
    messages = [ChatMessage(role="user", content=prompt)]
    return generate_chat_response(messages)


def run_cli() -> None:
    parser = argparse.ArgumentParser(description="Run a chat prompt.")
    parser.add_argument("prompt", type=str, help="The chat prompt to send.")
    args = parser.parse_args()

    try:
        print(run_cli_chat(args.prompt))
    except HTTPException as exc:
        parser.exit(status=1, message=f"Unable to run chat: {exc.detail}\n")


if __name__ == "__main__":
    run_cli()