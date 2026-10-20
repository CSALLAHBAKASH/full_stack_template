# Chat API

Set `GROQ_API_KEY` in the backend environment or in `backend/.env` to enable
chat. The backend loads that file relative to `settings.py` without overriding
environment variables supplied by the runtime. In Kubernetes, provide the key
through the existing backend Secret configured by the Helm chart's
`existingSecret` value.

`POST /chat` requires an authenticated workspace session and accepts up to 20
conversation messages. Each message must have a `user` or `assistant` role and
contain no more than 4,000 characters. The response contains the assistant's
reply. Chat history is sent by the client and is not stored by the backend.

`POST /chat/tools` uses the same authenticated request and response format, and
enables LLM tool-calling for addition, subtraction, multiplication, and
division. Arithmetic runs in the backend using validated numeric arguments;
division by zero and non-finite results are rejected.

The sequential learning examples and commands for running them are in
[`agentic_ai/README.md`](agentic_ai/README.md).
