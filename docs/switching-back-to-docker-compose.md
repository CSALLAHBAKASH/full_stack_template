# Switch Back from Kubernetes to Docker Compose

Use this guide after running the frontend and backend with Helm on the local
Docker Desktop Kubernetes cluster and wanting to run the full app with Docker
Compose again.

The local hybrid setup keeps PostgreSQL and Redis in Docker Compose while the
frontend and backend run in Kubernetes. The steps below remove the Helm-managed
app resources, keep the Compose database and cache data, and restart the
Compose app services.

## 1. Stop the Kubernetes port-forward

If a `kubectl port-forward` command is running in a terminal, focus that
terminal and press **Ctrl+C**. The host port must be available before Compose
starts the frontend.

## 2. Uninstall the Helm release

From the project root, remove the Helm release:

```bash
helm uninstall agent-workspace --namespace agent-workspace
```

This removes the Helm-managed frontend/backend deployments, services,
ConfigMap, and other release resources. The Helm migration Job is normally
deleted after it succeeds.

Confirm the app resources are gone:

```bash
helm list --namespace agent-workspace
kubectl get deployments,pods,services --namespace agent-workspace
```

The namespace and `agent-workspace-secrets` Secret are separate from the Helm
release and may remain. Keeping them is harmless and makes a future Helm
install easier. Do not delete the namespace just to switch runtimes.

## 3. Preserve and start PostgreSQL and Redis

The Compose PostgreSQL and Redis services hold the local hybrid app's data.
Keep their named volumes. Do **not** run `docker compose down -v` or remove
`postgres_data` / `redis_data` if you want to preserve database records and
Redis contents.

Start the database and cache if they are stopped:

```bash
docker compose up -d postgres redis
docker compose ps
```

Wait until both services report healthy before starting the application.

## 4. Start the frontend and backend with Compose

Build and start the app containers:

```bash
docker compose up -d --build frontend backend
```

Compose also waits for the database migration service and backend health check
as configured in `docker-compose.yml`. Check the resulting services:

```bash
docker compose ps
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

Open the app at <http://localhost:3000>.

## 5. Open the Compose app on an iPhone

For access from an iPhone on the same Wi-Fi:

1. Find the Mac's Wi-Fi IP:

   ```bash
   ipconfig getifaddr en0
   ```

2. Set `LAN_HOST` in `.env` to that IP address, for example:

   ```dotenv
   LAN_HOST=192.168.0.105
   ```

3. Recreate the frontend and backend so the development origin settings are
   reloaded:

   ```bash
   docker compose up -d --force-recreate frontend backend
   ```

4. On the iPhone, connected to the same non-guest Wi-Fi, open
   `http://<MAC-WI-FI-IP>:3000` in Safari.

If the Mac's Wi-Fi IP changes, update `LAN_HOST` and recreate those two
services again.

## 6. Optional cleanup notes

- The Compose database and Redis containers and their named volumes are
  independent of the Kubernetes namespace. Uninstalling Helm does not delete
  them.
- A later Helm install can reuse the existing Compose database and cache, or
  the app can continue using them through Compose.
- Do not delete the Kubernetes namespace or Secret unless you intentionally
  want to remove those Kubernetes resources. They are not needed to run the
  Compose app.
- Avoid `docker compose down -v` when local database data must be retained.

For the full setup and Helm deployment instructions, see
[local-development-and-helm.md](./local-development-and-helm.md).
