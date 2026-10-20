# Agentic AI learning path

The numbered modules are runnable lessons. Each lesson builds on the concepts
introduced before it. The first three examples are implemented; later lessons
are intentionally listed as a roadmap rather than empty placeholder modules.

## Learning sequence

1. `step_01_llm_chat.py` — call an LLM directly and expose a simple chat API.
2. `step_02_llm_with_tools.py` — bind arithmetic tools to an LLM and handle
   tool calls.
3. `step_03_langchain_agent.py` — use LangChain `create_agent` to run the
   model/tool loop with arithmetic, date/time, Wikipedia, and local text-file
   tools.
4. `step_04_agent_with_tools.py` — give an agent a typed toolset.
5. `step_05_agent_with_mcp.py` — connect an agent to MCP tools.
6. `step_06_langchain_chain.py` — compose `prompt | llm | StrOutputParser`.
7. `step_07_agent_arguments.py` — pass runtime arguments and configurable
   keyword arguments to agent invocations.
8. `step_08_agent_middleware.py` — inspect and modify agent execution with
   middleware.
9. `step_09_agent_human_approval.py` — add human approval to agent actions.
10. `step_10_langgraph_basics.py` — build a graph with state, nodes, and edges.
11. `step_11_langgraph_routing.py` — add conditional routing and loops.
12. `step_12_langgraph_persistence.py` — persist graph state with checkpoints.
13. `step_13_langgraph_streaming.py` — stream graph updates and model tokens.
14. `step_14_langgraph_human_in_loop.py` — interrupt and resume a graph for
    human input.
15. `step_15_langgraph_subgraphs.py` — compose and reuse subgraphs.

## Run the implemented lessons

From the repository root, with the backend virtual environment and
`GROQ_API_KEY` configured in the environment or `backend/.env`:

```bash
backend/.venv/bin/python -m backend.agentic_ai.step_01_llm_chat "Explain what an LLM is"
backend/.venv/bin/python -m backend.agentic_ai.step_02_llm_with_tools "What is 12 plus 8?"
backend/.venv/bin/python -m backend.agentic_ai.step_03_langchain_agent "What is 12 plus 8?"
backend/.venv/bin/python -m backend.agentic_ai.tools add_numbers 12 8
backend/.venv/bin/python backend/agentic_ai/tools/calculator.py
```

The corresponding authenticated API routes are `POST /chat`,
`POST /chat/tools`, and `POST /chat/agent`. All use the shared request schema
and provider settings. Step 02 implements the tool-calling loop explicitly;
step 03 delegates that loop to LangChain's `create_agent`. The workspace UI
also has separate Chat, Tools chat, and Agent tabs for comparing the flows.

Arithmetic tools live in `tools/calculator.py`, are exported from `tools`, and
can be run independently from the CLI using
`python -m backend.agentic_ai.tools <operation> <value>...`. Positional values
are mapped to the selected tool's argument names in schema order. For tools
that need keyword-only or optional arguments, pass them as one JSON object with
`--kwargs '{"name": value}'`. Values are parsed as JSON when possible, and
LangChain validates the resulting arguments against the tool schema. Supported
operations are `add_numbers`, `subtract_numbers`, `multiply_numbers`, and
`divide_numbers`. To smoke-test the `add_numbers` tool directly, run
`python backend/agentic_ai/tools/calculator.py`.

The LangChain agent also receives tools from `tools/standard.py`: it can get
the current local date/time, search Wikipedia, and create/read/append/replace/
delete `.txt` files in `backend/agentic_ai/agent_workspace/`. File operations
reject absolute paths and paths that escape this dedicated workspace. Wikipedia
search uses the public API and does not require an API key.
