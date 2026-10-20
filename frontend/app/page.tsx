"use client";

import {
  FormEvent,
  KeyboardEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import Link from "next/link";
import {
  Bot,
  Calculator,
  LayoutDashboard,
  Plus,
  Send,
  Sparkles,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const SESSION_IDLE_TIMEOUT_MS = 5 * 60 * 1000;
const SESSION_HEARTBEAT_INTERVAL_MS = 30 * 1000;

type User = {
  id: string;
  email: string;
  full_name: string;
  role: "admin" | "user";
  is_active: boolean;
  created_at: string;
};

type AuthConfig = {
  password_enabled: boolean;
  oidc_enabled: boolean;
};

type WorkspaceView = "dashboard" | "workspace" | "tools" | "agent";

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
};

function MarkdownContent({ content }: { content: string }) {
  return (
    <div className="markdown-content">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </div>
  );
}

class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function getApiErrorMessage(body: unknown): string | undefined {
  if (typeof body === "string") return body;
  if (Array.isArray(body)) {
    const messages = body
      .map((item) => {
        if (isRecord(item) && typeof item.msg === "string") {
          const location: Array<string | number> = Array.isArray(item.loc)
            ? item.loc.filter(
                (part: unknown): part is string | number =>
                  typeof part === "string" || typeof part === "number",
              )
            : [];
          return `${location.length ? `${location.join(".")}: ` : ""}${item.msg}`;
        }
        return getApiErrorMessage(item);
      })
      .filter((message): message is string => Boolean(message));
    return messages.length ? messages.join("; ") : undefined;
  }
  if (isRecord(body)) {
    for (const key of ["detail", "message", "error"]) {
      if (key in body) {
        const message = getApiErrorMessage(body[key]);
        if (message) return message;
      }
    }
    try {
      return JSON.stringify(body);
    } catch {
      return undefined;
    }
  }
  return undefined;
}

async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    credentials: "include",
    headers: {
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });
  if (response.status === 204) return undefined as T;

  const body: unknown = await response.json().catch(() => undefined);
  if (!response.ok) {
    throw new ApiError(
      getApiErrorMessage(body) ?? "Request failed. Please try again.",
      response.status,
    );
  }
  return body as T;
}

export default function Home() {
  const [authConfig, setAuthConfig] = useState<AuthConfig | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [activeView, setActiveView] = useState<WorkspaceView>("dashboard");
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [newUser, setNewUser] = useState({
    email: "",
    full_name: "",
    password: "",
    role: "user" as "admin" | "user",
  });
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatSubmitting, setChatSubmitting] = useState(false);
  const [chatError, setChatError] = useState("");
  const chatMessagesRef = useRef<HTMLDivElement>(null);
  const [toolMessages, setToolMessages] = useState<ChatMessage[]>([]);
  const [toolInput, setToolInput] = useState("");
  const [toolSubmitting, setToolSubmitting] = useState(false);
  const [toolError, setToolError] = useState("");
  const toolMessagesRef = useRef<HTMLDivElement>(null);
  const [agentMessages, setAgentMessages] = useState<ChatMessage[]>([]);
  const [agentInput, setAgentInput] = useState("");
  const [agentSubmitting, setAgentSubmitting] = useState(false);
  const [agentError, setAgentError] = useState("");
  const agentMessagesRef = useRef<HTMLDivElement>(null);

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  const loadUsers = useCallback(async () => {
    const result = await apiRequest<User[]>("/users");
    setUsers(result);
  }, []);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const config = await apiRequest<AuthConfig>("/auth/config");
        if (active) setAuthConfig(config);
        const currentUser = await apiRequest<User>("/auth/me");
        if (active) {
          setUser(currentUser);
          setActiveView(currentUser.role === "admin" ? "dashboard" : "workspace");
          if (currentUser.role === "admin") {
            const existingUsers = await apiRequest<User[]>("/users");
            if (active) setUsers(existingUsers);
          }
        }
      } catch (requestError) {
        if (
          active &&
          !(requestError instanceof ApiError && requestError.status === 401)
        ) {
          setError(
            requestError instanceof Error
              ? requestError.message
              : "Unable to connect to the API.",
          );
        }
      } finally {
        if (active) setLoading(false);
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const messageList = chatMessagesRef.current;
    messageList?.scrollTo({
      top: messageList.scrollHeight,
      behavior: "smooth",
    });
  }, [chatMessages, chatSubmitting]);

  useEffect(() => {
    const messageList = toolMessagesRef.current;
    messageList?.scrollTo({
      top: messageList.scrollHeight,
      behavior: "smooth",
    });
  }, [toolMessages, toolSubmitting]);

  useEffect(() => {
    const messageList = agentMessagesRef.current;
    messageList?.scrollTo({
      top: messageList.scrollHeight,
      behavior: "smooth",
    });
  }, [agentMessages, agentSubmitting]);

  useEffect(() => {
    if (!user?.id) return;

    let isActive = true;
    let lastActivity = Date.now();
    let idleTimer: number;

    async function expireSession(message: string) {
      if (!isActive) return;
      isActive = false;
      window.clearTimeout(idleTimer);
      try {
        await apiRequest<void>("/auth/logout", { method: "POST" });
      } catch (requestError) {
        const detail =
          requestError instanceof Error
            ? ` ${requestError.message}`
            : " The session cookie could not be cleared.";
        message += detail;
      } finally {
        setUser(null);
        setUsers([]);
        setChatMessages([]);
        setToolMessages([]);
        setAgentMessages([]);
        setError(message);
      }
    }

    function scheduleIdleExpiration() {
      window.clearTimeout(idleTimer);
      idleTimer = window.setTimeout(() => {
        void expireSession(
          "Your session expired after 5 minutes of inactivity. Please sign in again.",
        );
      }, SESSION_IDLE_TIMEOUT_MS);
    }

    function trackActivity() {
      lastActivity = Date.now();
      scheduleIdleExpiration();
    }

    async function refreshSession() {
      try {
        const currentUser = await apiRequest<User>("/auth/me");
        if (isActive) setUser(currentUser);
      } catch (requestError) {
        if (requestError instanceof ApiError && requestError.status === 401) {
          void expireSession("Your session expired. Please sign in again.");
        } else if (isActive) {
          setError(
            requestError instanceof Error
              ? `Unable to refresh your session. ${requestError.message}`
              : "Unable to refresh your session. Check your connection.",
          );
        }
      }
    }

    const activityEvents = [
      "pointerdown",
      "pointermove",
      "keydown",
      "scroll",
      "touchstart",
    ] as const;
    activityEvents.forEach((eventName) =>
      window.addEventListener(eventName, trackActivity, { passive: true }),
    );
    scheduleIdleExpiration();
    const heartbeatTimer = window.setInterval(() => {
      if (!isActive) return;
      if (document.visibilityState !== "visible") return;
      if (Date.now() - lastActivity >= SESSION_IDLE_TIMEOUT_MS) {
        void expireSession(
          "Your session expired after 5 minutes of inactivity. Please sign in again.",
        );
        return;
      }
      void refreshSession();
    }, SESSION_HEARTBEAT_INTERVAL_MS);

    return () => {
      isActive = false;
      window.clearTimeout(idleTimer);
      window.clearInterval(heartbeatTimer);
      activityEvents.forEach((eventName) =>
        window.removeEventListener(eventName, trackActivity),
      );
    };
  }, [user?.id]);

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const signedInUser = await apiRequest<User>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      setUser(signedInUser);
      setActiveView(signedInUser.role === "admin" ? "dashboard" : "workspace");
      setPassword("");
      if (signedInUser.role === "admin") await loadUsers();
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Unable to sign in.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function handleLogout() {
    setError("");
    try {
      await apiRequest<void>("/auth/logout", { method: "POST" });
      setUser(null);
      setUsers([]);
      setChatMessages([]);
      setToolMessages([]);
      setAgentMessages([]);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Unable to sign out.",
      );
    }
  }

  async function handleCreateUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setNotice("");
    setSubmitting(true);
    try {
      await apiRequest<User>("/users", {
        method: "POST",
        body: JSON.stringify(newUser),
      });
      setNewUser({ email: "", full_name: "", password: "", role: "user" });
      setNotice("User created successfully.");
      await loadUsers();
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Unable to create user.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function updateUser(target: User, changes: Partial<User>) {
    setError("");
    setNotice("");
    try {
      const updated = await apiRequest<User>(`/users/${target.id}`, {
        method: "PATCH",
        body: JSON.stringify(changes),
      });
      setUsers((existing) =>
        existing.map((item) => (item.id === updated.id ? updated : item)),
      );
      setNotice(`${updated.email} updated.`);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Unable to update user.",
      );
    }
  }

  async function refreshUsers() {
    setError("");
    try {
      await loadUsers();
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Unable to load users.",
      );
    }
  }

  async function handleChatSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const content = chatInput.trim();
    if (!content || chatSubmitting) return;

    const nextMessages = [
      ...chatMessages,
      { id: crypto.randomUUID(), role: "user" as const, content },
    ];
    setChatMessages(nextMessages);
    setChatError("");
    setChatSubmitting(true);
    try {
      const result = await apiRequest<{ reply: string }>("/chat", {
        method: "POST",
        body: JSON.stringify({
          messages: nextMessages
            .slice(-20)
            .map(({ role, content: messageContent }) => ({
              role,
              content: messageContent,
            })),
        }),
      });
      setChatMessages([
        ...nextMessages,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: result.reply,
        },
      ]);
      setChatInput("");
    } catch (requestError) {
      setChatError(
        requestError instanceof Error
          ? requestError.message
          : "Unable to send your message.",
      );
    } finally {
      setChatSubmitting(false);
    }
  }

  async function handleToolChatSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const content = toolInput.trim();
    if (!content || toolSubmitting) return;

    const nextMessages = [
      ...toolMessages,
      { id: crypto.randomUUID(), role: "user" as const, content },
    ];
    setToolMessages(nextMessages);
    setToolError("");
    setToolSubmitting(true);
    try {
      const result = await apiRequest<{ reply: string }>("/chat/tools", {
        method: "POST",
        body: JSON.stringify({
          messages: nextMessages
            .slice(-20)
            .map(({ role, content: messageContent }) => ({
              role,
              content: messageContent,
            })),
        }),
      });
      setToolMessages([
        ...nextMessages,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: result.reply,
        },
      ]);
      setToolInput("");
    } catch (requestError) {
      setToolError(
        requestError instanceof Error
          ? requestError.message
          : "Unable to send your message.",
      );
    } finally {
      setToolSubmitting(false);
    }
  }

  async function handleAgentChatSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const content = agentInput.trim();
    if (!content || agentSubmitting) return;

    const nextMessages = [
      ...agentMessages,
      { id: crypto.randomUUID(), role: "user" as const, content },
    ];
    setAgentMessages(nextMessages);
    setAgentError("");
    setAgentSubmitting(true);
    try {
      const result = await apiRequest<{ reply: string }>("/chat/agent", {
        method: "POST",
        body: JSON.stringify({
          messages: nextMessages
            .slice(-20)
            .map(({ role, content: messageContent }) => ({
              role,
              content: messageContent,
            })),
        }),
      });
      setAgentMessages([
        ...nextMessages,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: result.reply,
        },
      ]);
      setAgentInput("");
    } catch (requestError) {
      setAgentError(
        requestError instanceof Error
          ? requestError.message
          : "Unable to send your message.",
      );
    } finally {
      setAgentSubmitting(false);
    }
  }

  if (loading) {
    return (
      <main className="auth-shell">
        <div className="loading-card">Connecting to your workspace…</div>
      </main>
    );
  }

  if (!user) {
    return (
      <main className="auth-shell">
        <section className="login-card">
          <div className="brand-mark" aria-hidden="true">
            A
          </div>
          <p className="eyebrow">YOUR AI WORKSPACE</p>
          <h1>Welcome back</h1>
          <p className="muted">Sign in to continue to your workspace.</p>

          {error && <p className="alert alert-error">{error}</p>}

          {authConfig?.password_enabled && (
            <form className="form-stack" onSubmit={handleLogin}>
              <label>
                Email address
                <input
                  autoComplete="username"
                  autoFocus
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="you@example.com"
                  required
                />
              </label>
              <label>
                Password
                <input
                  autoComplete="current-password"
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="Enter your password"
                  required
                />
              </label>
              <button className="button button-primary button-wide" disabled={submitting}>
                {submitting ? "Signing in…" : "Sign in"}
              </button>
            </form>
          )}

          {authConfig?.oidc_enabled && (
            <>
              {authConfig.password_enabled && <div className="divider">or</div>}
              <form action="/api/auth/oidc/start" method="get">
                <button className="button button-secondary button-wide" type="submit">
                  Continue with your identity provider
                </button>
              </form>
            </>
          )}

          {!authConfig?.password_enabled && !authConfig?.oidc_enabled && (
            <p className="alert alert-error">
              No sign-in method is configured. Check the backend environment.
            </p>
          )}

          <p className="login-footnote">
            Accounts are provisioned by an administrator or your identity provider.
          </p>
        </section>
      </main>
    );
  }

  return (
    <main className="dashboard-shell">
      <header className="topbar">
        <Link className="brand" href="/" aria-label="Workspace home">
          <span className="brand-mark brand-mark-small" aria-hidden="true">
            A
          </span>
          <span>Agent Workspace</span>
        </Link>
        <nav className="workspace-nav" aria-label="Workspace views">
          <button
            className={`nav-tab ${activeView === "workspace" ? "nav-tab-active" : ""}`}
            aria-pressed={activeView === "workspace"}
            onClick={() => setActiveView("workspace")}
          >
            <Bot aria-hidden="true" size={16} strokeWidth={2} />
            Chat
          </button>
          <button
            className={`nav-tab ${activeView === "tools" ? "nav-tab-active" : ""}`}
            aria-pressed={activeView === "tools"}
            onClick={() => setActiveView("tools")}
          >
            <Calculator aria-hidden="true" size={16} strokeWidth={2} />
            Tools chat
          </button>
          <button
            className={`nav-tab ${activeView === "agent" ? "nav-tab-active" : ""}`}
            aria-pressed={activeView === "agent"}
            onClick={() => setActiveView("agent")}
          >
            <Sparkles aria-hidden="true" size={16} strokeWidth={2} />
            Agent
          </button>
          {user.role === "admin" && (
            <button
              className={`nav-tab ${activeView === "dashboard" ? "nav-tab-active" : ""}`}
              aria-pressed={activeView === "dashboard"}
              onClick={() => setActiveView("dashboard")}
            >
              <LayoutDashboard aria-hidden="true" size={16} strokeWidth={2} />
              Admin
            </button>
          )}
        </nav>
        <div className="account-menu">
          <div className="account-copy">
            <strong>{user.full_name || user.email}</strong>
            <span>{user.role}</span>
          </div>
          <button className="button button-quiet" onClick={handleLogout}>
            Sign out
          </button>
        </div>
      </header>

      <div className="dashboard-content">
        <section className="welcome-row">
          <div>
            <p className="eyebrow">
              {activeView === "dashboard" && user.role === "admin"
                ? "ACCESS MANAGEMENT"
                : activeView === "tools"
                  ? "TOOL-ENABLED ASSISTANT"
                  : activeView === "agent"
                    ? "LANGCHAIN AGENT"
                    : "YOUR AI WORKSPACE"}
            </p>
            <h1>
              {activeView === "dashboard" && user.role === "admin"
                ? "Admin dashboard"
                : activeView === "tools"
                  ? "Tools chat"
                  : activeView === "agent"
                    ? "LangChain agent"
                    : "Agent workspace"}
            </h1>
            <p className="muted">
              {activeView === "dashboard" && user.role === "admin"
                ? `Manage users and access for ${user.email}.`
                : activeView === "tools"
                  ? "Ask the assistant to calculate with its built-in math tools."
                  : activeView === "agent"
                    ? "Let the agent decide when to use its arithmetic tools."
                    : `Welcome back, ${user.full_name || user.email}.`}
            </p>
          </div>
          <span className={`role-pill ${user.role === "admin" ? "role-admin" : ""}`}>
            {user.role === "admin" ? "Administrator" : "Member"}
          </span>
        </section>

        {user.role === "admin" && activeView === "dashboard" ? (
          <>
            <section className="stats-grid" aria-label="Workspace summary">
              <article className="stat-card">
                <span className="stat-label">Total users</span>
                <strong>{users.length}</strong>
                <span className="stat-hint">Accounts in this workspace</span>
              </article>
              <article className="stat-card">
                <span className="stat-label">Active accounts</span>
                <strong>{users.filter((item) => item.is_active).length}</strong>
                <span className="stat-hint">Users who can sign in</span>
              </article>
              <article className="stat-card">
                <span className="stat-label">Your access</span>
                <strong>Admin</strong>
                <span className="stat-hint">Manage user access and roles</span>
              </article>
            </section>

            <section className="panel create-panel access-management-panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">ACCESS MANAGEMENT</p>
                  <h2>Add a user</h2>
                  <p className="muted">
                    Create a local account and choose its workspace role.
                  </p>
                </div>
              </div>
              <form className="create-user-form" onSubmit={handleCreateUser}>
                <label>
                  Full name
                  <input
                    value={newUser.full_name}
                    onChange={(event) =>
                      setNewUser({ ...newUser, full_name: event.target.value })
                    }
                    placeholder="Alex Morgan"
                  />
                </label>
                <label>
                  Email address
                  <input
                    type="email"
                    autoComplete="off"
                    value={newUser.email}
                    onChange={(event) =>
                      setNewUser({ ...newUser, email: event.target.value })
                    }
                    placeholder="alex@example.com"
                    required
                  />
                </label>
                <label>
                  Temporary password
                  <input
                    type="password"
                    autoComplete="new-password"
                    minLength={12}
                    value={newUser.password}
                    onChange={(event) =>
                      setNewUser({ ...newUser, password: event.target.value })
                    }
                    placeholder="At least 12 characters"
                    required
                  />
                </label>
                <label>
                  Role
                  <select
                    value={newUser.role}
                    onChange={(event) =>
                      setNewUser({
                        ...newUser,
                        role: event.target.value as "admin" | "user",
                      })
                    }
                  >
                    <option value="user">Member</option>
                    <option value="admin">Administrator</option>
                  </select>
                </label>
                <button className="button button-primary create-button" disabled={submitting}>
                  {submitting ? "Creating…" : "Create user"}
                </button>
              </form>
            </section>
            {(error || notice) && (
              <p
                className={`alert dashboard-notice ${error ? "alert-error" : "alert-success"}`}
                role={error ? "alert" : "status"}
              >
                {error || notice}
              </p>
            )}

            <section className="panel users-panel">
              <div className="panel-heading panel-heading-row">
                <div>
                  <p className="eyebrow">DIRECTORY</p>
                  <h2>Users</h2>
                </div>
                <button
                  className="button button-secondary"
                  onClick={() => void refreshUsers()}
                >
                  Refresh
                </button>
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>User</th>
                      <th>Role</th>
                      <th>Status</th>
                      <th>Joined</th>
                      <th aria-label="Actions" />
                    </tr>
                  </thead>
                  <tbody>
                    {users.map((item) => (
                      <tr key={item.id}>
                        <td>
                          <div className="user-cell">
                            <span className="avatar">
                              {(item.full_name || item.email).slice(0, 1).toUpperCase()}
                            </span>
                            <span>
                              <strong>{item.full_name || "Unnamed user"}</strong>
                              <small>{item.email}</small>
                            </span>
                          </div>
                        </td>
                        <td>
                          <select
                            aria-label={`Role for ${item.email}`}
                            value={item.role}
                            disabled={item.id === user.id}
                            onChange={(event) =>
                              void updateUser(item, {
                                role: event.target.value as "admin" | "user",
                              })
                            }
                          >
                            <option value="user">Member</option>
                            <option value="admin">Admin</option>
                          </select>
                        </td>
                        <td>
                          <span
                            className={`status-dot ${item.is_active ? "status-active" : ""}`}
                          />
                          {item.is_active ? "Active" : "Disabled"}
                        </td>
                        <td>{new Date(item.created_at).toLocaleDateString()}</td>
                        <td className="action-cell">
                          <button
                            className="button button-quiet"
                            disabled={item.id === user.id}
                            onClick={() =>
                              void updateUser(item, { is_active: !item.is_active })
                            }
                          >
                            {item.is_active ? "Disable" : "Enable"}
                          </button>
                        </td>
                      </tr>
                    ))}
                    {users.length === 0 && (
                      <tr>
                        <td className="empty-state" colSpan={5}>
                          No users found.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </section>
          </>
        ) : activeView === "agent" ? (
          <section className="agent-workspace" aria-label="LangChain agent chat">
            <header className="chat-header">
              <div className="chat-agent">
                <span className="agent-orb" aria-hidden="true">
                  <Sparkles size={22} />
                </span>
                <div>
                  <p className="eyebrow">LANGCHAIN AGENT</p>
                  <h2>Agent assistant</h2>
                  <span>The agent chooses and runs tools when useful.</span>
                </div>
              </div>
              <button
                className="button button-secondary new-chat-button"
                type="button"
                onClick={() => {
                  setAgentMessages([]);
                  setAgentError("");
                  setAgentInput("");
                }}
                disabled={agentSubmitting}
              >
                <Plus aria-hidden="true" size={16} />
                New chat
              </button>
            </header>

            <div
              className="chat-messages"
              ref={agentMessagesRef}
              aria-label="LangChain agent conversation"
              aria-live="polite"
            >
              {agentMessages.length === 0 ? (
                <div className="chat-empty-state">
                  <span className="chat-empty-icon" aria-hidden="true">
                    <Sparkles size={22} />
                  </span>
                  <strong>Ask the agent to solve a problem</strong>
                  <p>
                    LangChain manages the model and tool-calling loop for you.
                  </p>
                  <div className="chat-suggestions" aria-label="Suggested prompts">
                    {[
                      "What is 125 plus 348?",
                      "Multiply 24 by 19",
                      "Explain how you calculate 144 divided by 12",
                    ].map((suggestion) => (
                      <button
                        className="chat-suggestion"
                        key={suggestion}
                        type="button"
                        onClick={() => setAgentInput(suggestion)}
                      >
                        {suggestion}
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                agentMessages.map((message) => (
                  <article
                    className={`chat-message chat-message-${message.role}`}
                    key={message.id}
                  >
                    <span className="chat-message-avatar" aria-hidden="true">
                      {message.role === "assistant" ? (
                        <Sparkles size={16} />
                      ) : (
                        (user.full_name || user.email).slice(0, 1).toUpperCase()
                      )}
                    </span>
                    <div className="chat-message-content">
                      <span>{message.role === "assistant" ? "Agent" : "You"}</span>
                      <MarkdownContent content={message.content} />
                    </div>
                  </article>
                ))
              )}
              {agentSubmitting && (
                <div className="chat-message chat-message-assistant" role="status">
                  <span className="chat-message-avatar" aria-hidden="true">
                    <Sparkles size={16} />
                  </span>
                  <div className="chat-message-content">
                    <span>Agent</span>
                    <p className="chat-thinking">Thinking and choosing tools…</p>
                  </div>
                </div>
              )}
            </div>

            {agentError && (
              <p className="alert alert-error chat-error" role="alert">
                {agentError}
              </p>
            )}

            <form className="agent-composer" onSubmit={handleAgentChatSubmit}>
              <label htmlFor="agent-chat-prompt">Your message</label>
              <textarea
                id="agent-chat-prompt"
                value={agentInput}
                onChange={(event) => setAgentInput(event.target.value)}
                onKeyDown={handleComposerKeyDown}
                placeholder="Ask the agent to calculate or explain something…"
                maxLength={4000}
                disabled={agentSubmitting}
                rows={3}
              />
              <div className="composer-footer">
                <span>LangChain agent + arithmetic tools · ⌘/Ctrl + Enter to send</span>
                <button
                  className="button button-primary"
                  type="submit"
                  disabled={agentSubmitting || !agentInput.trim()}
                >
                  <Send aria-hidden="true" size={15} />
                  {agentSubmitting ? "Working…" : "Send"}
                </button>
              </div>
            </form>
          </section>
        ) : activeView === "tools" ? (
          <section className="agent-workspace" aria-label="Tool-enabled chat">
            <header className="chat-header">
              <div className="chat-agent">
                <span className="agent-orb" aria-hidden="true">
                  <Calculator size={22} />
                </span>
                <div>
                  <p className="eyebrow">TOOL-ENABLED ASSISTANT</p>
                  <h2>Math tools</h2>
                  <span>Add, subtract, multiply, or divide.</span>
                </div>
              </div>
              <button
                className="button button-secondary new-chat-button"
                type="button"
                onClick={() => {
                  setToolMessages([]);
                  setToolError("");
                  setToolInput("");
                }}
                disabled={toolSubmitting}
              >
                <Plus aria-hidden="true" size={16} />
                New chat
              </button>
            </header>

            <div
              className="chat-messages"
              ref={toolMessagesRef}
              aria-label="Tool chat conversation"
              aria-live="polite"
            >
              {toolMessages.length === 0 ? (
                <div className="chat-empty-state">
                  <span className="chat-empty-icon" aria-hidden="true">
                    <Calculator size={22} />
                  </span>
                  <strong>Ask me to calculate something</strong>
                  <p>
                    I can add, subtract, multiply, and divide using calculator
                    tools.
                  </p>
                  <div className="chat-suggestions" aria-label="Suggested calculations">
                    {[
                      "What is 125 plus 348?",
                      "Multiply 24 by 19",
                      "Divide 144 by 12",
                    ].map((suggestion) => (
                      <button
                        className="chat-suggestion"
                        key={suggestion}
                        type="button"
                        onClick={() => setToolInput(suggestion)}
                      >
                        {suggestion}
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                toolMessages.map((message) => (
                  <article
                    className={`chat-message chat-message-${message.role}`}
                    key={message.id}
                  >
                    <span className="chat-message-avatar" aria-hidden="true">
                      {message.role === "assistant" ? (
                        <Calculator size={16} />
                      ) : (
                        (user.full_name || user.email).slice(0, 1).toUpperCase()
                      )}
                    </span>
                    <div className="chat-message-content">
                      <span>{message.role === "assistant" ? "Assistant" : "You"}</span>
                      <MarkdownContent content={message.content} />
                    </div>
                  </article>
                ))
              )}
              {toolSubmitting && (
                <div className="chat-message chat-message-assistant" role="status">
                  <span className="chat-message-avatar" aria-hidden="true">
                    <Calculator size={16} />
                  </span>
                  <div className="chat-message-content">
                    <span>Assistant</span>
                    <p className="chat-thinking">Choosing and running a tool…</p>
                  </div>
                </div>
              )}
            </div>

            {toolError && (
              <p className="alert alert-error chat-error" role="alert">
                {toolError}
              </p>
            )}

            <form className="agent-composer" onSubmit={handleToolChatSubmit}>
              <label htmlFor="tool-chat-prompt">Your message</label>
              <textarea
                id="tool-chat-prompt"
                value={toolInput}
                onChange={(event) => setToolInput(event.target.value)}
                placeholder="Try: What is 125 plus 348?"
                maxLength={4000}
                disabled={toolSubmitting}
                onKeyDown={handleComposerKeyDown}
                rows={3}
              />
              <div className="composer-footer">
                <span>
                  Tools: add · subtract · multiply · divide · ⌘/Ctrl + Enter to
                  send
                </span>
                <button
                  className="button button-primary"
                  type="submit"
                  disabled={toolSubmitting || !toolInput.trim()}
                >
                  <Send aria-hidden="true" size={15} />
                  {toolSubmitting ? "Working…" : "Send"}
                </button>
              </div>
            </form>
          </section>
        ) : (
          <section className="agent-workspace" aria-label="Agent chat">
            <header className="chat-header">
              <div className="chat-agent">
                <span className="agent-orb" aria-hidden="true">
                  <Bot size={24} />
                </span>
                <div>
                  <p className="eyebrow">AGENT PLAYGROUND</p>
                  <h2>Chat assistant</h2>
                  <span>Ask a question or explore an idea.</span>
                </div>
              </div>
              <button
                className="button button-secondary new-chat-button"
                type="button"
                onClick={() => {
                  setChatMessages([]);
                  setChatError("");
                  setChatInput("");
                }}
                disabled={chatSubmitting}
              >
                <Plus aria-hidden="true" size={16} />
                New chat
              </button>
            </header>

            <div
              className="chat-messages"
              ref={chatMessagesRef}
              aria-label="Conversation"
              aria-live="polite"
            >
              {chatMessages.length === 0 ? (
                <div className="chat-empty-state">
                  <span className="chat-empty-icon" aria-hidden="true">
                    <Bot size={22} />
                  </span>
                  <strong>What can I help you with?</strong>
                  <p>Your conversation will appear here.</p>
                  <div className="chat-suggestions" aria-label="Suggested prompts">
                    {[
                      "Explain a concept in simple terms",
                      "Help me draft an email",
                      "Write a Python function",
                    ].map((suggestion) => (
                      <button
                        className="chat-suggestion"
                        key={suggestion}
                        type="button"
                        onClick={() => setChatInput(suggestion)}
                      >
                        {suggestion}
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                chatMessages.map((message) => (
                  <article
                    className={`chat-message chat-message-${message.role}`}
                    key={message.id}
                  >
                    <span className="chat-message-avatar" aria-hidden="true">
                      {message.role === "assistant" ? (
                        <Bot size={16} />
                      ) : (
                        (user.full_name || user.email).slice(0, 1).toUpperCase()
                      )}
                    </span>
                    <div className="chat-message-content">
                      <span>{message.role === "assistant" ? "Assistant" : "You"}</span>
                      <MarkdownContent content={message.content} />
                    </div>
                  </article>
                ))
              )}
              {chatSubmitting && (
                <div className="chat-message chat-message-assistant" role="status">
                  <span className="chat-message-avatar" aria-hidden="true">
                    <Bot size={16} />
                  </span>
                  <div className="chat-message-content">
                    <span>Assistant</span>
                    <p className="chat-thinking">Thinking…</p>
                  </div>
                </div>
              )}
            </div>

            {chatError && (
              <p className="alert alert-error chat-error" role="alert">
                {chatError}
              </p>
            )}

            <form className="agent-composer" onSubmit={handleChatSubmit}>
              <label htmlFor="agent-prompt">Your message</label>
              <textarea
                id="agent-prompt"
                value={chatInput}
                onChange={(event) => setChatInput(event.target.value)}
                placeholder="Message the assistant…"
                maxLength={4000}
                disabled={chatSubmitting}
                onKeyDown={handleComposerKeyDown}
                rows={3}
              />
              <div className="composer-footer">
                <span>⌘/Ctrl + Enter to send</span>
                <button
                  className="button button-primary"
                  type="submit"
                  disabled={chatSubmitting || !chatInput.trim()}
                >
                  <Send aria-hidden="true" size={15} />
                  {chatSubmitting ? "Sending…" : "Send"}
                </button>
              </div>
            </form>
          </section>
        )}
        <footer className="dashboard-footer">Agent Workspace · Secure access</footer>
      </div>
    </main>
  );
}
