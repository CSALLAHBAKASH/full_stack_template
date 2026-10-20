# Agent Workspace Template

Reusable local-to-Kubernetes foundation for agentic applications: Next.js,
FastAPI, PostgreSQL, Redis, session-based authentication, role-based access, and
Helm deployment.

## Local development

1. Copy `.env.example` to `.env` and replace `SESSION_SECRET`,
   `BOOTSTRAP_ADMIN_PASSWORD`, and `POSTGRES_PASSWORD`. The checked-in Compose
   fallbacks are development defaults only.
2. Start the stack from the project root:

   ```bash
   docker compose up --build
   ```

3. Open the frontend at <http://localhost:3000>. The default local bootstrap
   account is `admin@example.com`; use the password from `.env`.

To open the app on a phone on the same Wi-Fi, set `LAN_HOST` in `.env` to your
computer's Wi-Fi IP address (for example, `192.168.1.100`), then run
`docker compose up -d --force-recreate frontend backend`. On your phone, visit
`http://<LAN_HOST>:3000`. If your computer gets a new IP, update `LAN_HOST` and
recreate those services again.

The frontend proxies `/api/*` to the backend, so browser requests and the
HttpOnly session cookie stay same-origin. The backend connects to PostgreSQL and
Redis using Compose service names. A one-shot `migrate` service applies Alembic
migrations before the API starts.

| Service | Local address |
| --- | --- |
| Frontend | <http://localhost:3000> |
| Backend API (direct) | <http://localhost:8000> |
| API docs | <http://localhost:8000/docs> |
| Liveness | <http://localhost:8000/health> |
| Readiness (PostgreSQL + Redis) | <http://localhost:8000/ready> |
| PostgreSQL | `localhost:5432` |
| Redis | `localhost:6379` |

PostgreSQL and Redis use named volumes. `docker compose down` preserves them;
`docker compose down -v` removes persistent data. Both password authentication
and optional OIDC are supported. To enable OIDC, configure the `OIDC_*` values
in `.env` and register `OIDC_REDIRECT_URI` with your identity provider. OIDC
users with verified email addresses are linked to existing accounts by email
or provisioned with the `user` role. Local passwords are stored as bcrypt
hashes; browser sessions are opaque, HttpOnly cookies backed by Redis.
Sessions expire after five minutes without user activity; authenticated API
requests refresh the session while the workspace is being used.
OIDC ID tokens are validated using the provider's RS256 signing keys.

The first admin is created once from `BOOTSTRAP_ADMIN_EMAIL` and
`BOOTSTRAP_ADMIN_PASSWORD`. Changing these values does not reset an existing
account. Administrators can create local users, assign `admin` or `user` roles,
and disable or re-enable accounts from the dashboard. Admins can also switch to
the agent workspace from the top navigation; regular members open directly into
the same workspace. The chat composer remains disabled until an agent runtime
endpoint is connected. API routes enforce administrative permissions
independently of the UI.

## Local Kubernetes with Helm

Docker Compose can remain running only for PostgreSQL and Redis while the
frontend and API run in Kubernetes. This workflow assumes Docker Desktop
Kubernetes is enabled and uses `host.docker.internal` for the Compose services.
For the complete step-by-step workflow, troubleshooting, and switching between
Compose and Helm, see
[docs/local-development-and-helm.md](./docs/local-development-and-helm.md).
To remove the Helm app and return to Compose while preserving local database
data, see
[docs/switching-back-to-docker-compose.md](./docs/switching-back-to-docker-compose.md).

```bash
docker compose up -d postgres redis
docker build -t agent-workspace/backend:local -f backend/Dockerfile backend
docker build -t agent-workspace/frontend:local -f frontend/Dockerfile frontend
kubectl config use-context docker-desktop
kubectl create namespace agent-workspace --dry-run=client -o yaml | kubectl apply -f -
```

Create the Kubernetes Secret `agent-workspace-secrets` with `DATABASE_URL`,
`REDIS_URL`, `SESSION_SECRET`, `BOOTSTRAP_ADMIN_EMAIL`,
`BOOTSTRAP_ADMIN_PASSWORD`, and `COOKIE_SECURE`. For the Compose defaults, the
connection URLs are
`postgresql+psycopg://app:devpassword@host.docker.internal:5432/app` and
`redis://host.docker.internal:6379/0`; use `COOKIE_SECURE=false` for local HTTP.
Use your own secret values if you changed the Compose credentials.

For the checked-in local Compose defaults, create the Secret with:

```bash
kubectl create secret generic agent-workspace-secrets \
  --namespace agent-workspace \
  --from-literal=DATABASE_URL='postgresql+psycopg://app:devpassword@host.docker.internal:5432/app' \
  --from-literal=REDIS_URL='redis://host.docker.internal:6379/0' \
  --from-literal=SESSION_SECRET='local-development-session-secret-change-me' \
  --from-literal=BOOTSTRAP_ADMIN_EMAIL='admin@example.com' \
  --from-literal=BOOTSTRAP_ADMIN_PASSWORD='local-admin-password-change-me' \
  --from-literal=COOKIE_SECURE='false' \
  --dry-run=client -o yaml | kubectl apply -f -
```

Then deploy the locally built images (replace the host with your computer's
Wi-Fi IP to use the app from another device):

```bash
FRONTEND_ORIGIN=http://localhost:3000
LAN_HOST=192.168.1.100
helm upgrade --install agent-workspace ./infra/helm/agent-workspace \
  --namespace agent-workspace \
  --set fullnameOverride=agent-workspace \
  --set existingSecret=agent-workspace-secrets \
  --set backend.image.repository=agent-workspace/backend \
  --set backend.image.tag=local \
  --set frontend.image.repository=agent-workspace/frontend \
  --set frontend.image.tag=local \
  --set-string frontendUrl="$FRONTEND_ORIGIN" \
  --set-string "corsOrigins=$FRONTEND_ORIGIN\\,http://$LAN_HOST:3000"
kubectl rollout status deployment/agent-workspace-backend -n agent-workspace
kubectl rollout status deployment/agent-workspace-frontend -n agent-workspace
```

Stop only the Compose app containers when switching the app to Helm; the
database and cache containers remain running:

```bash
docker compose stop frontend backend
kubectl port-forward --address 0.0.0.0 -n agent-workspace \
  service/agent-workspace-frontend 3000:3000
```

Keep the port-forward command running and open `http://<computer-wi-fi-ip>:3000`
on the phone. To switch the app back, stop the port-forward with Ctrl+C and run
`docker compose up -d frontend backend`.

## Backend development

Run database migrations before starting the API outside Compose:

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn main:app --reload
```

Set `DATABASE_URL`, `REDIS_URL`, and `SESSION_SECRET` in the environment first.
New schema changes should be made through Alembic migrations.

## Kubernetes / Helm

The chart deploys the frontend and API; it intentionally does not install
PostgreSQL or Redis. Use managed database/cache services and provide their
connection strings through an existing Kubernetes Secret. Build and publish
production images, then set their repositories and tags in the chart values.

Create a Secret containing at least `DATABASE_URL`, `REDIS_URL`, and
`SESSION_SECRET` (32+ random bytes). Set `BOOTSTRAP_ADMIN_EMAIL` and
`BOOTSTRAP_ADMIN_PASSWORD` there to provision the first admin. Add
`OIDC_CLIENT_SECRET` if OIDC is enabled.

```bash
helm upgrade --install agent-workspace ./infra/helm/agent-workspace \
  --namespace agent-workspace --create-namespace \
  --set backend.image.repository=REGISTRY/agent-workspace-backend \
  --set backend.image.tag=VERSION \
  --set frontend.image.repository=REGISTRY/agent-workspace-frontend \
  --set frontend.image.tag=VERSION \
  --set existingSecret=agent-workspace-secrets \
  --set frontendUrl=https://workspace.example.com \
  --set ingress.enabled=true \
  --set ingress.host=workspace.example.com
```

The chart runs `alembic upgrade head` as a Helm pre-install/pre-upgrade Job,
then starts the API with liveness and readiness probes. Configure the optional
`oidc` chart values and put its client secret in the existing Secret to enable
OIDC. TLS termination and DNS are provided by the cluster ingress controller.

Treat all passwords and session secrets as sensitive. The Compose defaults and
local HTTP setup are for development, not production.
