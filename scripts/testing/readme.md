# Integration smoke tests

These tests create a temporary company and user, ingest the fictional English documents in `RAG/`, exercise the six cases in `testcases/`, and attempt to clean up their test data. They call Azure OpenAI or OpenAI and incur API costs. Use a disposable local database.

Start the local stack following the [root README](../../README.md), and configure global system prompts in the administration UI (or use the optional seed job).

From this directory, create and activate a Python environment:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

On PowerShell, activate with `.venv\Scripts\Activate.ps1`.

Export `ADMIN_USERNAME` and `ADMIN_PASSWORD` matching the running backend, and either `AZURE_API_KEY`, `AZURE_ENDPOINT`, `AZURE_VERSION` or `OPENAI_API_KEY` for the test/grading client. The application stack itself still requires Azure. Compose does not export the root `.env` into this shell. Do not place credentials in the committed `config.json`.

```sh
python smoke_test.py
```

The committed config targets local ports 5000 and 8000. For overrides, copy it to ignored `config.local.json`, modify endpoints/timeouts/model settings, and set `SMOKE_CONFIG=config.local.json`. Run from this directory so relative fixture paths resolve correctly. Reports go to ignored `out/` and may include conversation content and deployment information; do not publish them.

The English fixture suite covers strategy conflicts, technical risks, missing follow-up, international customer tasks, ERP observations, and a multi-turn strategy question. The fixtures are examples, not customer records. Grading uses an LLM and is not deterministic. Inspect cleanup output if a run fails.
