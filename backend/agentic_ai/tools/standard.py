import json
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

from langchain_core.tools import tool

AGENT_WORKSPACE = Path(__file__).resolve().parent.parent / "agent_workspace"
_WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"


def _workspace_file(file_path: str) -> Path:
    relative_path = Path(file_path)
    if relative_path.is_absolute() or relative_path.suffix.lower() != ".txt":
        raise ValueError("Use a relative path to a .txt file in the agent workspace.")

    workspace = AGENT_WORKSPACE.resolve()
    resolved_path = (workspace / relative_path).resolve()
    if not resolved_path.is_relative_to(workspace):
        raise ValueError("File operations are limited to the agent workspace.")
    return resolved_path


@tool
def get_current_datetime() -> str:
    """Get the current local date and time, including the timezone."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


@tool
def search_wikipedia(query: str) -> str:
    """Search Wikipedia and return a short plain-text summary."""
    if not query.strip():
        raise ValueError("The Wikipedia search query cannot be empty.")

    parameters = urlencode(
        {
            "action": "query",
            "format": "json",
            "prop": "extracts",
            "explaintext": 1,
            "exsentences": 3,
            "redirects": 1,
            "titles": query.strip(),
        }
    )
    request = Request(
        f"{_WIKIPEDIA_API}?{parameters}",
        headers={"User-Agent": "AgenticAILearningApp/1.0"},
    )
    try:
        with urlopen(request, timeout=10) as response:
            result = json.load(response)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Wikipedia search failed: {exc}") from exc

    pages = result.get("query", {}).get("pages", {})
    page = next(iter(pages.values()), {})
    extract = page.get("extract", "").strip()
    title = page.get("title", "")
    if not extract or not title:
        return f"No Wikipedia summary found for {query!r}."

    article_url = "https://en.wikipedia.org/wiki/" + quote(title.replace(" ", "_"))
    return f"{title}\n{extract}\nSource: {article_url}"


@tool
def create_text_file(file_path: str, content: str) -> str:
    """Create a new .txt file in the agent workspace without overwriting files."""
    path = _workspace_file(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as file:
        file.write(content)
    return f"Created {path.relative_to(AGENT_WORKSPACE.resolve())}."


@tool
def read_text_file(file_path: str) -> str:
    """Read a .txt file from the agent workspace."""
    path = _workspace_file(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Text file not found in agent workspace: {file_path}")
    return path.read_text(encoding="utf-8")


@tool
def append_to_text_file(file_path: str, content: str) -> str:
    """Append text to an existing .txt file in the agent workspace."""
    path = _workspace_file(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Text file not found in agent workspace: {file_path}")
    with path.open("a", encoding="utf-8") as file:
        file.write(content)
    return f"Updated {path.relative_to(AGENT_WORKSPACE.resolve())}."


@tool
def replace_text_in_file(file_path: str, old_text: str, new_text: str) -> str:
    """Replace one exact text occurrence in an agent-workspace .txt file."""
    if not old_text:
        raise ValueError("The text to replace cannot be empty.")
    path = _workspace_file(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Text file not found in agent workspace: {file_path}")

    contents = path.read_text(encoding="utf-8")
    occurrences = contents.count(old_text)
    if occurrences != 1:
        raise ValueError(
            f"Expected exactly one occurrence of the text to replace; found {occurrences}."
        )
    path.write_text(contents.replace(old_text, new_text, 1), encoding="utf-8")
    return f"Updated {path.relative_to(AGENT_WORKSPACE.resolve())}."


@tool
def delete_text_file(file_path: str) -> str:
    """Delete one .txt file from the agent workspace."""
    path = _workspace_file(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Text file not found in agent workspace: {file_path}")
    path.unlink()
    return f"Deleted {path.relative_to(AGENT_WORKSPACE.resolve())}."


standard_tools = [
    get_current_datetime,
    search_wikipedia,
    create_text_file,
    read_text_file,
    append_to_text_file,
    replace_text_in_file,
    delete_text_file,
]
