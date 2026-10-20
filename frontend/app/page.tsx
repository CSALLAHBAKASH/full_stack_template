"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Bot, LayoutDashboard } from "lucide-react";

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

type WorkspaceView = "dashboard" | "workspace";

class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
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

  const body = (await response.json().catch(() => ({}))) as {
    detail?: string;
  };
  if (!response.ok) {
    throw new ApiError(body.detail ?? "Request failed. Please try again.", response.status);
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
        {user.role === "admin" && (
          <nav
            className="workspace-nav"
            aria-label="Workspace views"
          >
            <button
              className={`nav-tab ${activeView === "dashboard" ? "nav-tab-active" : ""}`}
              aria-pressed={activeView === "dashboard"}
              onClick={() => setActiveView("dashboard")}
            >
              <LayoutDashboard aria-hidden="true" size={16} strokeWidth={2} />
              Admin dashboard
            </button>
            <button
              className={`nav-tab ${activeView === "workspace" ? "nav-tab-active" : ""}`}
              aria-pressed={activeView === "workspace"}
              onClick={() => setActiveView("workspace")}
            >
              <Bot aria-hidden="true" size={16} strokeWidth={2} />
              Agent workspace
            </button>
          </nav>
        )}
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
                : "YOUR AI WORKSPACE"}
            </p>
            <h1>
              {activeView === "dashboard" && user.role === "admin"
                ? "Admin dashboard"
                : "Agent workspace"}
            </h1>
            <p className="muted">
              {activeView === "dashboard" && user.role === "admin"
                ? `Manage users and access for ${user.email}.`
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
        ) : (
          <section className="agent-workspace" aria-label="Agent workspace">
            <div className="agent-welcome">
              <span className="agent-orb" aria-hidden="true">
                ✳
              </span>
              <p className="eyebrow">AGENT PLAYGROUND</p>
              <h2>Build something intelligent.</h2>
              <p>
                Your workspace is ready. Connect an agent runtime to start a
                conversation and explore your agentic applications.
              </p>
            </div>
            <div className="agent-connection">
              <span className="connection-indicator" />
              <div>
                <strong>Agent runtime not connected</strong>
                <span>
                  Add your agent API endpoint to enable chat in this workspace.
                </span>
              </div>
            </div>
            <form className="agent-composer" onSubmit={(event) => event.preventDefault()}>
              <label htmlFor="agent-prompt">Your message</label>
              <textarea
                id="agent-prompt"
                placeholder="Connect an agent runtime to start sending messages…"
                disabled
                rows={3}
              />
              <div className="composer-footer">
                <span>Agent integrations can be configured for each project.</span>
                <button className="button button-primary" type="button" disabled>
                  Send message
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
