# AI-BASS system components

The runtime stack is defined in [docker-compose.dev.yaml](docker-compose.dev.yaml).

## Data flow

1. The [Vue admin UI](frontend/admin-ui) calls the [Flask backend](apps/admin-backend/app.py), directly during frontend development or through Nginx `/api/` in Docker.
2. The backend manages companies, users, settings, metadata, uploaded files, cloud/email integrations, scheduled synchronization and reports in MongoDB `companydb`.
3. Document ingestion sends content to the [LightRAG API](apps/lightrag-service/main.py). The supplied configuration uses PostgreSQL/pgvector storage, Azure embeddings and a persistent working directory. MongoDB/search support is also included.
4. The [web chat API](apps/chat-service/main.py) uses the shared [chat engine](apps/chat-service/core/chat_engine.py) to combine company context, retrieval, conversation history and configured prompts. Conversations and generated memories are persisted in MongoDB.
5. The optional [WhatsApp service](apps/chat-service/whatsapp.py) handles provider webhooks, supported file/audio messages and optional forwarding to a separate course deployment.
6. The [log service](apps/log-service/main.py) stores interactions, classifies turns with Azure OpenAI and records token usage for administration reports.

## Services and state

| Compose service | Role | Persistent state |
| --- | --- | --- |
| `admin-frontend` | Built Vue application served by Nginx | None |
| `backend` | Administration, ingestion and integrations | MongoDB |
| `chat-service` | Web chat and external chat API | MongoDB |
| `whatsapp-service` | Optional WhatsApp webhook (`whatsapp` profile) | MongoDB |
| `log-service` | Interaction classification and logging | MongoDB |
| `lightrag-service` | Retrieval and document indexing | PostgreSQL, MongoDB and `lightrag_data` |
| `mongo` | MongoDB replica set | `mongo-data` |
| `mongot` | MongoDB community search | `mongot_data` |
| `lightrag-postgres` | PostgreSQL with pgvector | `lightrag-pg-data` |
| `db-init` | Optional fictional sample data (`seed` profile) | Writes through the backend API |

The seed job waits for the backend, MongoDB, search startup and LightRAG. It is not started by the default stack. Search credentials are shared through `MONGOT_PASSWORD`; its password file is generated inside the search container, not supplied from the repository.

## Configuration and operations

[.env.example](.env.example) describes the supported Compose configuration. Public URLs, provider credentials and application secrets are deployment inputs. Local service names are intentionally retained for container communication.

The [scripts directory](scripts) contains MongoDB backups, retention cleanup, deployment helpers and migration tools. `deploy.course.sh` is a legacy entrypoint with the same configurable `COMPOSE_FILE` default as `deploy.sh`; this repository does not contain a separate course Compose file. The [smoke tests](scripts/testing/readme.md) ingest fictional English documents and exercise six retrieval scenarios.

Refer to [README.md](README.md) for setup, endpoints, integration configuration and the limits of the local development configuration.
