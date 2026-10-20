import argparse
import logging
import math
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_groq import ChatGroq

if __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models import User
from schemas import ChatMessage, ChatRequest, ChatResponse
from security import get_current_user
from settings import settings

logger = logging.getLogger(__name__)
router = APIRouter()


def _finite_result(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("The result is outside the supported numeric range.")
    return value


@tool
def add_numbers(first: float, second: float) -> float:
    """Add two numbers."""
    return _finite_result(first + second)


@tool
def subtract_numbers(first: float, second: float) -> float:
    """Subtract the second number from the first."""
    return _finite_result(first - second)


@tool
def multiply_numbers(first: float, second: float) -> float:
    """Multiply two numbers."""
    return _finite_result(first * second)


@tool
def divide_numbers(first: float, second: float) -> float:
    """Divide the first number by the second."""
    if second == 0:
        raise ValueError("Cannot divide by zero.")
    return _finite_result(first / second)


tools = [add_numbers, subtract_numbers, multiply_numbers, divide_numbers]
tools_by_name = {calculator.name: calculator for calculator in tools}
max_tool_rounds = 4


def generate_tool_chat_response(messages: list[ChatMessage]) -> str:
    if not settings.groq_api_key:
        raise HTTPException(
            status_code=503,
            detail="Tool chat is not configured. Set the GROQ_API_KEY environment variable.",
        )

    conversation = [
        SystemMessage(
            content=(
                "You are a helpful assistant with access to arithmetic tools for "
                "addition, subtraction, multiplication, and division. Use the "
                "tools to calculate results rather than doing arithmetic mentally. "
                "Explain the result clearly and never claim a tool ran if it did not."
            )
        ),
        *[
            HumanMessage(content=message.content)
            if message.role == "user"
            else AIMessage(content=message.content)
            for message in messages
        ],
    ]

    try:
        model = ChatGroq(
            model="openai/gpt-oss-20b",
            api_key=settings.groq_api_key,
        ).bind_tools(tools)

        for _ in range(max_tool_rounds):
            response = model.invoke(conversation)
            conversation.append(response)
            if not response.tool_calls:
                if not isinstance(response.content, str) or not response.content.strip():
                    logger.error("Tool chat returned an empty or unsupported response.")
                    raise HTTPException(
                        status_code=502,
                        detail="The chat provider returned an invalid response.",
                    )
                return response.content.strip()

            for tool_call in response.tool_calls:
                calculator = tools_by_name.get(tool_call["name"])
                if calculator is None:
                    raise ValueError("The model requested an unsupported tool.")
                result = calculator.invoke(tool_call["args"])
                conversation.append(
                    ToolMessage(
                        content=str(result),
                        tool_call_id=tool_call["id"],
                    )
                )

        raise HTTPException(
            status_code=502,
            detail="The assistant exceeded the maximum number of tool calls.",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Tool chat request failed.")
        raise HTTPException(
            status_code=502,
            detail="The assistant could not complete the tool request.",
        ) from exc


@router.post("/chat/tools", response_model=ChatResponse)
def tool_chat(
    payload: ChatRequest,
    _: User = Depends(get_current_user),
) -> ChatResponse:
    return ChatResponse(reply=generate_tool_chat_response(payload.messages))


def run_tool_chat(prompt: str) -> str:
    """Run a single tool-enabled prompt for local testing."""
    message = ChatMessage(role="user", content=prompt)
    return generate_tool_chat_response([message])


def run_cli() -> None:
    parser = argparse.ArgumentParser(
        description="Try the tool-enabled assistant from the command line."
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        default="What is 12 plus 8?",
        help="A prompt to send to the tool-enabled assistant.",
    )
    args = parser.parse_args()

    try:
        print(run_tool_chat(args.prompt))
    except HTTPException as exc:
        parser.exit(
            status=1,
            message=f"Unable to run tool chat: {exc.detail}\n",
        )


if __name__ == "__main__":
    run_cli()
