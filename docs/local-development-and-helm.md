# Local Development and Helm Deployment

This guide records the local Docker Compose setup and the current hybrid local
Kubernetes workflow used by this project. It covers running the application
locally, switching the frontend and backend to Helm, connecting from an iPhone
on the same Wi-Fi, verifying the services, and switching back.

## 1. Choose a local runtime

There are two supported local workflows:

| Workflow | Frontend and backend | PostgreSQL and Redis |
| --- | --- | --- |
| Compose | Docker Compose containers | Docker Compose containers |
| Hybrid Helm | Kubernetes deployments and pods | Docker Compose containers, accessed from Kubernetes through `host.docker.internal` |

In the hybrid workflow, seeing two application pods in Kubernetes is expected.
PostgreSQL and Redis are separate Compose containers, not Kubernetes pods. The
Helm chart intentionally deploys only the frontend and backend; production
deployments should normally use managed or separately operated database and
cache services.

## 2. Run everything with Docker Compose

From the project root:

1. Copy `.env.example` to `.env`.
2. Set local values for `POSTGRES_PASSWORD`, `SESSION_SECRET`, and
   `BOOTSTRAP_ADMIN_PASSWORD`. Use a session secret with at least 32 random
   bytes. Do not use development defaults outside a private local environment.
3. To test from another device, set `LAN_HOST` to the Mac's Wi-Fi IP. On macOS,
   find it with:

   ```bash
   ipconfig getifaddr en0
   ```

   If that returns no address, check the active network interface in macOS
   Network settings.
4. Start the stack:

   ```bash
   docker compose up --build
   ```

5. Open `http://localhost:3000`. The bootstrap account email defaults to
   `admin@example.com`; sign in with the value of `BOOTSTRAP_ADMIN_PASSWORD`.

Compose starts the frontend, backend, a one-shot database migration service,
PostgreSQL, and Redis. PostgreSQL and Redis data are stored in named volumes.
`docker compose down` preserves those volumes. `docker compose down -v` removes
them and their data; do not use it unless you intend to delete the local data.

Useful checks:

```bash
docker compose ps
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

## 3. Prepare the Docker Desktop Kubernetes cluster

The hybrid procedure below assumes Docker Desktop Kubernetes is enabled and its
context is named `docker-desktop`.

1. Start only the Compose database and cache:

   ```bash
   docker compose up -d postgres redis
   ```

2. Confirm they are healthy:

   ```bash
   docker compose ps
   ```

3. Select the Docker Desktop context and create the namespace:

   ```bash
   kubectl config use-context docker-desktop
   kubectl create namespace agent-workspace \
     --dry-run=client -o yaml | kubectl apply -f -
   ```

4. Check that the cluster can reach the Compose services using the host
   gateway:

   ```bash
   kubectl run --rm --attach --restart=Never db-connectivity-check \
     --image=postgres:17-alpine --command -- \
     pg_isready -h host.docker.internal -p 5432 -U app -d app

   kubectl run --rm --attach --restart=Never redis-connectivity-check \
     --image=redis:7-alpine --command -- \
     redis-cli -h host.docker.internal -p 6379 ping
   ```

   These example checks use the Compose defaults (`app` database/user and
   Redis without a password). Adjust the PostgreSQL check if `.env` uses
   different values.

## 4. Build the local application images

Build the production images from the project root. Give each update a new tag
so Kubernetes pulls/runs the intended local image:

```bash
docker build -t agent-workspace/backend:local \
  -f backend/Dockerfile backend
docker build -t agent-workspace/frontend:local \
  -f frontend/Dockerfile frontend
```

Docker Desktop Kubernetes uses the Docker Desktop image store, so locally built
images can be referenced by the chart without pushing them to a registry.

## 5. Create or update the Kubernetes Secret

The backend and migration Job both need database, Redis, and authentication
settings. Create the Secret in the application namespace. The following values
are examples for the Compose defaults; replace passwords and the session
secret with the actual values configured in `.env`:

```bash
kubectl create secret generic agent-workspace-secrets \
  --namespace agent-workspace \
  --from-literal=DATABASE_URL='postgresql+psycopg://app:REPLACE_WITH_POSTGRES_PASSWORD@host.docker.internal:5432/app' \
  --from-literal=REDIS_URL='redis://host.docker.internal:6379/0' \
  --from-literal=SESSION_SECRET='REPLACE_WITH_A_RANDOM_SECRET_OF_AT_LEAST_32_BYTES' \
  --from-literal=BOOTSTRAP_ADMIN_EMAIL='admin@example.com' \
  --from-literal=BOOTSTRAP_ADMIN_PASSWORD='REPLACE_WITH_BOOTSTRAP_ADMIN_PASSWORD' \
  --from-literal=COOKIE_SECURE='false' \
  --dry-run=client -o yaml | kubectl apply -f -
```

`COOKIE_SECURE=false` is needed when using local plain HTTP. For OIDC, also add
the provider-specific settings and `OIDC_CLIENT_SECRET` to the Secret, and
register the correct callback URL with the identity provider.

## 6. Deploy or update the app with Helm

Set the Mac's Wi-Fi IP and configure both the localhost and Wi-Fi browser
origins. The escaped comma in `corsOrigins` is required by Helm's `--set-string`
parser so it treats the list as one value.

```bash
LAN_HOST="$(ipconfig getifaddr en0)"
FRONTEND_ORIGIN="http://${LAN_HOST}:3000"

helm upgrade --install agent-workspace ./infra/helm/agent-workspace \
  --namespace agent-workspace \
  --set fullnameOverride=agent-workspace \
  --set existingSecret=agent-workspace-secrets \
  --set backend.image.repository=agent-workspace/backend \
  --set backend.image.tag=local \
  --set frontend.image.repository=agent-workspace/frontend \
  --set frontend.image.tag=local \
  --set-string frontendUrl="$FRONTEND_ORIGIN" \
  --set-string "corsOrigins=http://localhost:3000\\,${FRONTEND_ORIGIN}"

kubectl rollout status deployment/agent-workspace-backend \
  --namespace agent-workspace
kubectl rollout status deployment/agent-workspace-frontend \
  --namespace agent-workspace
```

The chart runs `alembic upgrade head` as a Helm pre-install/pre-upgrade Job
before starting or updating the backend. The Job is removed after successful
completion, so it may not appear in Docker Desktop's Jobs list after deployment.

Check the application and service resources:

```bash
helm status agent-workspace --namespace agent-workspace
kubectl get deployments,pods,services --namespace agent-workspace
kubectl logs deployment/agent-workspace-backend --namespace agent-workspace
docker compose ps
```

Expected local hybrid state: two ready Kubernetes deployments/pods (frontend
and backend), and healthy Compose containers for PostgreSQL and Redis. The
frontend proxies `/api/*` to the Kubernetes backend, keeping browser API calls
and the session cookie same-origin.

## 7. Open the Helm app on the Mac or iPhone

The frontend Service is internal to Kubernetes. Start a port-forward from the
project machine and leave the terminal running:

```bash
kubectl port-forward --address 0.0.0.0 \
  --namespace agent-workspace \
  service/agent-workspace-frontend 3000:3000
```

- On the Mac, open `http://localhost:3000`.
- On an iPhone connected to the same Wi-Fi, open
  `http://<MAC-WI-FI-IP>:3000` in Safari. For example:
  `http://192.168.0.105:3000`.

If the page does not load, confirm the phone and Mac are on the same non-guest
Wi-Fi, check that the Mac's IP has not changed, and allow the connection through
the macOS firewall if prompted. Stop the port-forward with Ctrl+C when finished.
The port-forward is a local-development access method, not a production ingress.

## 8. Switch back to Docker Compose

Stop the port-forward with Ctrl+C, then restart the application services:

```bash
docker compose up -d --build frontend backend
docker compose ps
```

This reuses the same Compose PostgreSQL and Redis containers and their named
volumes. The Helm release remains installed until explicitly removed.
For the complete safe cleanup procedure, including uninstalling the Helm app
without removing Compose database data, see
[switching-back-to-docker-compose.md](./switching-back-to-docker-compose.md).

## 9. Troubleshoot origin errors

An `Untrusted request origin` response means the browser's origin is missing
from the backend's configured `corsOrigins`.

1. Check the Helm ConfigMap:

   ```bash
   kubectl get configmap agent-workspace-config \
     --namespace agent-workspace \
     -o jsonpath='{.data.CORS_ORIGINS}{"\n"}'
   ```

2. Include every browser origin used (for example, both
   `http://localhost:3000` and `http://<MAC-WI-FI-IP>:3000`) in the Helm
   `corsOrigins` value.
3. After changing a ConfigMap-backed environment variable, restart the backend
   so the process reads the new value:

   ```bash
   kubectl rollout restart deployment/agent-workspace-backend \
     --namespace agent-workspace
   kubectl rollout status deployment/agent-workspace-backend \
     --namespace agent-workspace
   ```

The production frontend image does not use Next.js development HMR origin
checks; the backend's origin allowlist still applies to cookie-authenticated
mutations.

## 10. Update the UI and deploy it to Helm

For a frontend-only change:

1. Edit the relevant frontend source. Dashboard markup is in
   `frontend/app/page.tsx`; shared styles are in
   `frontend/app/globals.css`.
2. Validate the frontend:

   ```bash
   cd frontend
   npm run lint
   npm run build
   cd ..
   ```

3. Build the updated image with a new tag:

   ```bash
   docker build -t agent-workspace/frontend:my-change \
     -f frontend/Dockerfile frontend
   ```

4. Update the Helm release:

   ```bash
   helm upgrade agent-workspace ./infra/helm/agent-workspace \
     --namespace agent-workspace \
     --reuse-values \
     --set frontend.image.tag=my-change \
     --wait --timeout 3m
   kubectl rollout status deployment/agent-workspace-frontend \
     --namespace agent-workspace
   ```

5. Refresh the browser. For example, the admin dashboard notification is
   rendered below the Access Management panel in `page.tsx`; its spacing is
   controlled by `.access-management-panel` and `.dashboard-notice` in
   `globals.css`.

For backend changes, build and set a new backend image tag instead. A Helm
upgrade runs the migration hook before updating the backend deployment.

## 11. Remove the local Helm app

Uninstalling the Helm release removes its application resources, but does not
remove the separate Compose database/cache containers or their named volumes:

```bash
helm uninstall agent-workspace --namespace agent-workspace
```

The namespace and Kubernetes Secret are separate resources and are not
necessarily removed by uninstalling the release. Keep the Secret if you plan
to reinstall; do not delete namespace resources unless you intend to remove
them.
