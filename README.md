# Kubernetes Capacity Agent

Web dashboard and CLI for Kubernetes capacity analysis, scheduling insights,
and operational recommendations. The application supports account-scoped
cluster connections and encrypts uploaded kubeconfigs at rest.

## Run with Docker Compose

Requirements: Docker Engine and the Docker Compose plugin.

Create a local `.env` file (never commit it) and set a persistent Fernet key:

```bash
printf 'CAPACITY_AGENT_ENCRYPTION_KEY=%s\n' \
  "$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" \
  > .env
```

Keep this key safe and stable. Replacing or losing it makes stored kubeconfigs
unreadable. Then start the application:

```bash
docker compose up --build -d
docker compose logs -f
```

By default, Compose binds the dashboard to `127.0.0.1:8080`. For remote access,
put it behind HTTPS and configure secure cookies; do not expose the application
directly to the public internet. Application state is stored in the Compose
volume `capacity-agent-data`.

## Connect a Kubernetes cluster

Sign in to the dashboard, open **Cluster**, upload a kubeconfig, validate the
connection, and select the active cluster. The application server must be able
to reach the Kubernetes API endpoint in the kubeconfig. Avoid kubeconfigs that
depend on local exec plugins or external certificate files.

## Security and operational notes

- Use a unique, persistent encryption key per installation and store it in a
  secret manager or protected deployment environment.
- Back up the key and application database together, and test restoration.
- The initial account model does not yet support inviting coworkers,
  role-based access, email verification/recovery, or automated login-abuse
  protections. Review these limits before production or commercial use.
- Keep cluster-changing operations behind explicit approval and validate
  recommendations with the cluster owner.
- Never commit `.env`, kubeconfigs, private keys, application state, backups, or
  customer-generated reports.

See [docs/MULTI_TENANT.md](docs/MULTI_TENANT.md) for server configuration and
cluster onboarding details.
