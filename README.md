# AI-BASS

AI-BASS is a company knowledge and decision-support platform. It combines a Vue administration interface, web and WhatsApp chat, document retrieval with LightRAG, conversation memories, and usage reporting. Documents can be uploaded manually or synchronized from Google Drive, OneDrive, and email.

## Repository

| Directory | Purpose |
| --- | --- |
| `frontend/admin-ui` | Vue 3 / Vite administration UI with English and Finnish localization |
| `apps/admin-backend` | Flask administration API, document ingestion, integrations and scheduled synchronization |
| `apps/chat-service` | FastAPI web chat and separate Flask WhatsApp webhook |
| `apps/lightrag-service` | LightRAG retrieval with PostgreSQL/pgvector and MongoDB storage support |
| `apps/log-service` | Interaction logging and LLM classification |
| `mongodb` | Local MongoDB replica-set and search-service configuration |
| `scripts` | Optional example data, migration, backup, deployment and smoke-test utilities |

See [SYSTEM_COMPONENTS.md](SYSTEM_COMPONENTS.md) for the runtime data flow.

## Local setup

Requirements: Docker Engine with Docker Compose v2, and an Azure OpenAI resource. The resource needs chat deployments named `gpt-4o` and `gpt-4o-mini`, and a `text-embedding-3-small` embedding deployment producing 1536-dimensional vectors. The LightRAG deployment names can be overridden in `.env`; some classification/reporting calls use `gpt-4o-mini` directly. Audio transcription additionally requires the `whisper` deployment.

1. Create local configuration:

   ```sh
   cp .env.example .env
   ```

2. Fill in `AZURE_API_KEY`, `AZURE_ENDPOINT`, `ADMIN_PASSWORD`, `JWT_SECRET`, `EMAIL_ENCRYPTION_KEY`, `POSTGRES_PASSWORD`, and `MONGOT_PASSWORD`. Compose rejects missing or empty required values. Use independent random values for each secret. For example, generate each password/signing secret with:

   ```sh
   python -c 'import secrets; print(secrets.token_hex(32))'
   ```

   Generate a Fernet-compatible email encryption key with:

   ```sh
   python -c 'import base64, secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())'
   ```

   Keep the encryption key stable for an existing database: changing it makes previously encrypted integration credentials unreadable. Rotate existing credentials deliberately; changing `POSTGRES_PASSWORD` in `.env` does not change the password in an already initialized PostgreSQL volume.

3. Validate configuration and start the stack:

   ```sh
   docker compose -f docker-compose.dev.yaml config --quiet
   docker compose -f docker-compose.dev.yaml up --build -d
   docker compose -f docker-compose.dev.yaml ps
   ```

4. Open the admin UI at `http://localhost:8080` and sign in using `ADMIN_USERNAME` and `ADMIN_PASSWORD` from `.env`. Create companies and users and configure global prompts under settings. Web chat is available at `http://localhost:8000`; users need a phone number and an admin password set on their user record.

   For a disposable local database, you can instead load fictional example companies, users, metadata and default prompts:

   ```sh
   docker compose -f docker-compose.dev.yaml --profile seed run --rm db-init
   ```

   Seeding is optional, creates data through the admin API, and may trigger billable Azure ingestion. It skips insertion if existing company data is detected. Do not use it to migrate an existing database. Existing stored prompts are not changed by updating these source files.

| Local endpoint | Purpose |
| --- | --- |
| `http://localhost:8080` | Admin UI and `/api/` proxy |
| `http://localhost:5000/health` | Admin API health |
| `http://localhost:8000` | Web chat |
| `http://localhost:9001/health` | LightRAG health |
| `http://localhost:8010` | Internal logging API (no browser homepage) |

The MongoDB, search and PostgreSQL ports are bound to loopback for local tools. Compose service names (such as `mongo` and `backend`) are internal DNS names, not deployment-specific server addresses. `0.0.0.0` binds servers inside containers; `127.0.0.1` and the Nginx Docker DNS address are intentional local infrastructure addresses.

To stop services while retaining data:

```sh
docker compose -f docker-compose.dev.yaml down
```

Persistent state is held in named volumes. Removing volumes deletes database and retrieval data.

## Optional integrations

- **Google Drive / Gmail:** set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `GOOGLE_REDIRECT_URI`; register the exact callback URI with the provider and connect the account from the company page.
- **OneDrive / Microsoft email:** set `MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET`, `MICROSOFT_TENANT_ID`, and `MICROSOFT_REDIRECT_URI`; register the callback URI and connect from the company page.
- **Generic IMAP:** configure the account through the company page. Stored integration credentials use `EMAIL_ENCRYPTION_KEY`.
- **WhatsApp:** fill in the `WHATSAPP_*` settings, then run `docker compose -f docker-compose.dev.yaml --profile whatsapp up --build -d`. The webhook listens on local port 8888 at `/webhook`; an externally reachable HTTPS reverse proxy is needed for provider callbacks. `WHATSAPP_VERIFY_TOKEN` is a value you generate and also configure with the provider.
- **Chat links:** set `ADMIN_PUBLIC_URL` and `CHAT_PUBLIC_URL` to the externally visible URLs when deploying elsewhere.
- **Course forwarding:** optionally configure `COURSE_URL` and `COURSE_API_SECRET`. The receiving chat deployment must use the same secret.

Never put secrets in `VITE_*` variables: these become public browser code. The Docker build explicitly sets the public API path to `/api/` and excludes local environment files from its context.

## Development and verification

For frontend development, install Node.js 22 and run:

```sh
cd frontend/admin-ui
npm install
npm run dev
```

The source defaults to the local backend on port 5000. Run `npm run build` to validate the frontend bundle. Python services have individual `requirements.txt` files and Dockerfiles. Use isolated environments when running them outside Docker; Compose `.env` values are not automatically exported to host processes.

Run the offline publication checks with Python 3 and PyYAML:

```sh
python -m pip install PyYAML
python scripts/check_publication.py
```

See [the smoke-test instructions](scripts/testing/readme.md) for integration tests, which require running services and LLM credentials. Python dependencies currently use unpinned versions, and there is no frontend dependency lockfile; dependency resolution and image builds must be verified in the target environment.

## Deployment and publication notes

The supplied Compose file is a **local development configuration**, not a hardened production deployment. MongoDB authentication is disabled in that configuration; several internal service endpoints and chat authentication paths need a separate production security review. Keep internal services private, configure TLS and access controls, and review authentication and authorization before exposing a deployment. The optional Nginx TLS templates use reserved example domains and certificate paths that must be replaced for a real deployment.

`.gitignore` and per-build-context `.dockerignore` files exclude local environment files, keys, logs, caches and common runtime artifacts. Do not commit database dumps, smoke-test reports, uploaded documents or real customer data. English is used for source text and example prompts; Finnish UI translations are in `frontend/admin-ui/src/locales/fi.json`.

Any credentials previously embedded in copied source/configuration must be revoked or rotated before publication, including cloud/API keys, OAuth secrets, WhatsApp credentials, signing/encryption secrets and passwords. Cleaning the working tree does not revoke credentials or remove them from other repositories, backups or previously published history. This checkout's branch/tag history contains only the original README, license and ignore file; imported application files were untracked at the time of cleanup. Local tool recovery references and private recovery archives may still contain the original files. Publish reviewed files and normal branches only; do not distribute the `.git` directory, recovery archives, or all refs using a mirror push.

The deployment scripts operate on the configured Compose project. Backups in `scripts/backup_db.sh` cover MongoDB `companydb` only; PostgreSQL and other volumes require separate backup procedures.

## License

[MIT](LICENSE).
