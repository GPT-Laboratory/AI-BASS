#!/usr/bin/env python3
import os
import re
import json
import time
import glob
import uuid
import logging
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime, timezone

import requests
from websocket import create_connection

# --- LLM clients (OpenAI / Azure OpenAI) ---
from openai import OpenAI, AzureOpenAI
from openai import APIConnectionError, APITimeoutError, APIStatusError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s]: %(message)s")
log = logging.getLogger("smoke")

# ---------- Config ----------

def load_config(path: str) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {p.resolve()}")
    with p.open("r", encoding="utf-8") as f:
        cfg = json.load(f)

    # Set debug logging if requested
    if cfg.get("DEBUG", False):
        log.setLevel(logging.DEBUG)
        log.debug("Debug logging enabled")

    return cfg

def cfg_value(cfg: Dict[str, Any], *keys: str, default: Optional[str] = None) -> Optional[str]:
    for k in keys:
        v = cfg.get(k)
        if v is not None and v != "":
            return str(v)
    return default

def apply_llm_env_from_cfg(cfg: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """
    Read LLM keys from the same config file and also export to ENV so
    downstream components (if any) can pick them up.
    Supports both UPPER and lower aliases in the config.
    """
    openai_key      = cfg_value(cfg, "OPENAI_API_KEY", "openai_key")
    azure_key       = cfg_value(cfg, "AZURE_API_KEY", "azure_key")
    azure_endpoint  = cfg_value(cfg, "AZURE_ENDPOINT", "azure_endpoint")
    azure_version   = cfg_value(cfg, "AZURE_VERSION", "azure_version")

    if openai_key:     os.environ["OPENAI_API_KEY"] = openai_key
    if azure_key:      os.environ["AZURE_API_KEY"] = azure_key
    if azure_endpoint: os.environ["AZURE_ENDPOINT"] = azure_endpoint
    if azure_version:  os.environ["AZURE_VERSION"]  = azure_version

    return {
        "openai_key": openai_key,
        "azure_key": azure_key,
        "azure_endpoint": azure_endpoint,
        "azure_version": azure_version,
    }

# ---------- Helpers ----------

def api(base: str, path: str) -> str:
    return f"{base.rstrip('/')}{path}"

def auth_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

def read_all_json_recursive(root_dir: Path) -> List[Path]:
    return [Path(p) for p in glob.glob(str(root_dir / "**" / "*.json"), recursive=True)]

def _mask(s: Optional[str]) -> str:
    if not s:
        return ""
    if len(s) <= 10:
        return "*" * len(s)
    return "[configured]"

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _json_from_text(txt: str) -> Optional[dict]:
    """
    Try to parse strict JSON. If that fails, try to extract the first {...} block.
    """
    try:
        return json.loads(txt)
    except Exception:
        pass
    m = re.search(r"\{(?:[^{}]|(?R))*\}", txt, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None

def _is_metadata_message(msg: str) -> bool:
    """
    Check if a WebSocket message is metadata (sources/debug_info) rather than the actual LLM response.
    The chat service sends JSON messages with {"type": "sources"} or {"type": "debug_info"}.
    """
    try:
        data = json.loads(msg)
        if isinstance(data, dict) and "type" in data:
            msg_type = data.get("type")
            return msg_type in ("sources", "debug_info")
    except (json.JSONDecodeError, ValueError):
        pass
    return False

def _receive_llm_response(ws, max_attempts: int = 5) -> str:
    """
    Receive messages from WebSocket until we get the actual LLM response (non-JSON text).
    The chat service may send:
    1. {"type": "sources", "data": [...]} - Skip this
    2. "Actual LLM response text" - Return this
    3. {"type": "debug_info", "data": {...}} - Skip this

    Args:
        ws: WebSocket connection
        max_attempts: Maximum number of messages to try receiving

    Returns:
        The actual LLM response text (non-metadata message)

    Raises:
        Exception if no valid response is received
    """
    for attempt in range(max_attempts):
        msg = ws.recv()

        # Skip metadata messages (sources, debug_info)
        if _is_metadata_message(msg):
            log.debug(f"Skipping metadata message (attempt {attempt + 1}/{max_attempts})")
            continue

        # This should be the actual LLM response
        log.debug(f"Received LLM response (length={len(msg)})")
        return msg

    raise Exception(f"Failed to receive LLM response after {max_attempts} attempts")

# ---------- Core ops against Admin API ----------

def login_admin(base: str, username: str, password: str) -> str:
    r = requests.post(api(base, "/login"), json={"username": username, "password": password}, timeout=20)
    r.raise_for_status()
    return r.json()["token"]

def create_company(base: str, token: str, company_doc: Dict[str, Any]) -> str:
    r = requests.post(api(base, "/companies"), headers=auth_headers(token), json=company_doc, timeout=20)
    r.raise_for_status()
    return r.json()["id"]

def create_user(base: str, token: str, user_doc: Dict[str, Any]) -> str:
    r = requests.post(api(base, "/users"), headers=auth_headers(token), json=user_doc, timeout=20)
    r.raise_for_status()
    return r.json()["id"]

def add_metadata(base: str, token: str, meta_doc: Dict[str, Any]) -> str:
    r = requests.post(api(base, "/metadata"), headers=auth_headers(token), json=meta_doc, timeout=60)
    r.raise_for_status()
    return r.json()["_id"]

def get_rag_status(base: str, token: str, company_id: str) -> List[Dict[str, Any]]:
    """
    Get RAG sync status for all documents of a company
    Returns list of {_id, rag_sync_status}
    """
    r = requests.get(api(base, f"/metadata/company/{company_id}/rag-status"), headers=auth_headers(token), timeout=20)
    r.raise_for_status()
    return r.json()

def wait_for_rag_insertion(base: str, token: str, company_id: str, doc_ids: List[str], timeout: int = 300, poll_interval: int = 5) -> bool:
    """
    Poll the RAG status endpoint until all documents are either 'inserted' or 'error'

    Args:
        base: API base URL
        token: Auth token
        company_id: Company ID to poll
        doc_ids: List of document IDs to wait for
        timeout: Maximum time to wait in seconds (default 5 minutes)
        poll_interval: Time between polls in seconds (default 5 seconds)

    Returns:
        True if all documents reached terminal state (inserted or error)
        False if timeout reached
    """
    start_time = time.time()
    doc_id_set = set(doc_ids)

    log.info(f"Waiting for {len(doc_ids)} documents to be inserted into RAG...")

    while time.time() - start_time < timeout:
        try:
            statuses = get_rag_status(base, token, company_id)

            # Build status map for our documents
            status_map = {item["_id"]: item["rag_sync_status"] for item in statuses if item["_id"] in doc_id_set}

            # Count statuses
            waiting = sum(1 for s in status_map.values() if s == "waiting")
            processing = sum(1 for s in status_map.values() if s == "processing")
            inserted = sum(1 for s in status_map.values() if s == "inserted")
            error = sum(1 for s in status_map.values() if s == "error")
            unknown = len(doc_id_set) - len(status_map)

            log.info(f"RAG status: waiting={waiting}, processing={processing}, inserted={inserted}, error={error}, unknown={unknown}")

            # Check if all documents are done (inserted or error)
            if waiting == 0 and processing == 0 and unknown == 0:
                if error > 0:
                    log.warning(f"{error} document(s) had RAG insertion errors")
                log.info(f"All documents processed. {inserted} inserted, {error} errors")
                return True

            # Wait before next poll
            time.sleep(poll_interval)

        except Exception as e:
            log.error(f"Error polling RAG status: {e}")
            time.sleep(poll_interval)

    log.error(f"Timeout waiting for RAG insertion after {timeout} seconds")
    return False

def delete_user(base: str, token: str, user_id: str) -> None:
    r = requests.delete(api(base, f"/users/{user_id}"), headers=auth_headers(token), timeout=20)
    if r.status_code not in (200, 404):
        r.raise_for_status()

def delete_company(base: str, token: str, company_id: str) -> None:
    r = requests.delete(api(base, f"/companies/{company_id}"), headers=auth_headers(token), timeout=20)
    if r.status_code not in (200, 404):
        r.raise_for_status()

def delete_company_metadata_bulk(base: str, token: str, company_id: str) -> int:
    r = requests.get(api(base, f"/metadata/company/{company_id}"), headers=auth_headers(token), timeout=30)
    if r.status_code == 404:
        return 0
    r.raise_for_status()
    items = r.json()
    count = 0
    for m in items:
        mid = m.get("_id", {}).get("$oid")
        if not mid:
            continue
        dr = requests.delete(api(base, f"/metadata/{mid}"), headers=auth_headers(token), timeout=20)
        if dr.status_code in (200, 404):
            count += 1
        else:
            dr.raise_for_status()
    return count

# ---------- RAG ingestion (JSON only: {"type": "...", "description": "..."} ) ----------

def load_rag_docs(rag_root: Path) -> List[Tuple[Dict[str, Any], Optional[str]]]:
    files = read_all_json_recursive(rag_root)
    out: List[Tuple[Dict[str, Any], Optional[str]]] = []
    for f in files:
        try:
            with f.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            description = str(data.get("description", "")).strip()
            if not description:
                log.warning(f"Skip (no description): {f}")
                continue
            meta = {
                "type": "manual_upload_file",
                "content": {
                    "description": description,
                    "full_content": description
                },
                "manual_upload": {
                    "file_name": str(f.relative_to(rag_root)),
                    "file_size": len(description.encode("utf-8")),
                    "mime_type": "application/json",
                    "file_extension": ".json"
                }
            }
            out.append((meta, str(f.relative_to(rag_root))))
        except Exception as e:
            log.error(f"Failed to parse RAG JSON {f}: {e}")
    return out

# ---------- Grading System ----------

def calculate_test_score(eval_result: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calculate a graded score (0-100) for a test case evaluation.

    Score components:
    - Expected findings: (hits / required) * findings_weight
    - Acceptance criteria: (passed / total) * acceptance_weight
    - Unexpected penalty: -(hits / total_unexpected) * penalty_weight

    Returns dict with score, components, and pass status.
    """
    grading_cfg = cfg.get("grading", {})

    findings_weight = grading_cfg.get("expected_findings_weight", 40)
    acceptance_weight = grading_cfg.get("acceptance_criteria_weight", 50)
    penalty_weight = grading_cfg.get("unexpected_penalty_weight", 10)
    passing_threshold = grading_cfg.get("passing_threshold", 75)

    # Expected findings score
    expected_hits = eval_result.get("expected_hits", 0)
    expected_required = eval_result.get("expected_required", 1)
    findings_score = (expected_hits / max(expected_required, 1)) * findings_weight

    # Acceptance criteria score
    acceptance_passed = eval_result.get("acceptance_passed", 0)
    acceptance_total = eval_result.get("acceptance_total", 1)
    acceptance_score = (acceptance_passed / max(acceptance_total, 1)) * acceptance_weight

    # Unexpected hits penalty
    unexpected_hits = eval_result.get("unexpected_hits", [])
    unexpected_count = len(unexpected_hits)
    # Assume max penalty if we have any unexpected hits (could be refined)
    unexpected_penalty = min(unexpected_count, 1) * penalty_weight

    # Calculate final score
    raw_score = findings_score + acceptance_score - unexpected_penalty
    final_score = max(0, min(100, raw_score))  # Clamp to [0, 100]

    # Pass/fail based on threshold
    passed = final_score >= passing_threshold

    return {
        "score": round(final_score, 2),
        "passed": passed,
        "components": {
            "findings_score": round(findings_score, 2),
            "acceptance_score": round(acceptance_score, 2),
            "unexpected_penalty": round(unexpected_penalty, 2)
        },
        "threshold": passing_threshold
    }

# ---------- LLM evaluation ----------

class LLM:
    def __init__(self, cfg: Dict[str, Any]):
        # decide provider from env (already set by apply_llm_env_from_cfg)
        self.cfg = cfg
        self.azure_key = os.getenv("AZURE_API_KEY")
        self.azure_endpoint = os.getenv("AZURE_ENDPOINT")
        self.azure_version = os.getenv("AZURE_VERSION", "2024-02-01")
        self.openai_key = os.getenv("OPENAI_API_KEY")

        # model or deployment name
        self.model = (
            cfg.get("GPT_CHAT_MODEL")
            or cfg.get("gpt_model")
            or "gpt-4o-mini"
        )

        self.timeout_s = float(cfg.get("CHAT_TIMEOUT_SECONDS", 20))
        self.max_tokens = int(cfg.get("CHAT_MAX_TOKENS", 900))

        if self.azure_key and self.azure_endpoint:
            self.provider = "azure"
            self.client = AzureOpenAI(
                api_key=self.azure_key,
                api_version=self.azure_version,
                azure_endpoint=self.azure_endpoint,
                timeout=self.timeout_s,
            )
            log.info(f"LLM: Using Azure OpenAI (deployment='{self.model}')")
        elif self.openai_key:
            self.provider = "openai"
            self.client = OpenAI(
                api_key=self.openai_key,
                timeout=self.timeout_s,
            )
            log.info(f"LLM: Using OpenAI (model='{self.model}')")
        else:
            raise RuntimeError("No LLM credentials found (Azure or OpenAI).")

    def chat(self, messages: List[Dict[str, str]], temperature: float = 0.0) -> str:
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=self.max_tokens,
            )
            return (resp.choices[0].message.content or "").strip()
        except (APITimeoutError, APIConnectionError, APIStatusError) as e:
            raise RuntimeError(f"LLM API error: {type(e).__name__}: {e}") from e
        except Exception as e:
            raise RuntimeError(f"LLM unexpected error: {e}") from e

def build_eval_messages(case: dict, payload: Dict[str, Any]) -> List[Dict[str, str]]:
    # Prepare content shown to the evaluator
    if "prompt_sequence" in case and isinstance(case["prompt_sequence"], list):
        user_part = {
            "prompt_sequence": case.get("prompt_sequence", []),
        }
        assistant_part = {
            "replies": payload.get("replies", []),
        }
    else:
        user_part = {
            "prompt": case.get("prompt", ""),
        }
        assistant_part = {
            "reply": payload.get("reply", ""),
        }

    wrapper = {
        "case_id": case.get("id", ""),
        "title": case.get("title", ""),
        "language": "fi",
        "expected_findings": case.get("expected_findings", []),
        "acceptance_criteria": case.get("acceptance_criteria", []),
        "unexpected_examples": case.get("unexpected_examples", []),
        "user_requests": user_part,
        "assistant_answers": assistant_part,
    }

    system = (
        "You are a test evaluator for a Finnish RAG chatbot. "
        "Evaluate the assistant's answers against the provided test case. "
        "Be reasonable and allow partial credit: "
        "- Accept date variations (e.g., '1.9.2025', '01.09.2025', '2025-09-01' are all valid) "
        "- Focus on semantic correctness over exact formatting "
        "- If a finding is substantially present (80%+ correct), count it as a hit "
        "- For acceptance criteria, use good judgment: minor formatting issues should not cause failure "
        "- Only mark unexpected_hits for actual problems, not minor variations "
        "Return ONLY a single valid JSON object, no markdown, no commentary."
    )

    # JSON schema we want back
    schema = {
        "passed": "boolean — true iff ALL acceptance criteria pass, required expected findings are met, and no unexpected examples appear.",
        "expected_required": "integer — how many expected findings are required (e.g. parse 'At least one'==1 or 'All four'==4; otherwise total).",
        "expected_hits": "integer — how many of the expected findings are clearly present in the assistant answer(s).",
        "acceptance": [
            {
                "criterion": "string — verbatim acceptance criterion",
                "passed": "boolean",
                "reason": "string — brief justification in Finnish"
            }
        ],
        "unexpected_hits": ["string — list of unexpected example strings that appear in the answer"],
        "notes": ["string — short evaluator notes in Finnish"]
    }

    instructions = (
        "INSTRUCTIONS:\n"
        "1) Read expected_findings and acceptance_criteria carefully.\n"
        "2) Determine expected_required from the criteria text (e.g. 'At least one' => 1; 'All four' => 4; "
        "otherwise equal to the number of expected_findings).\n"
        "3) Count expected_hits based on whether each finding is SUBSTANTIALLY present in the answers. "
        "Be lenient with date formats, label variations, and minor formatting differences. "
        "If 80%+ of the finding content is present, count it as a hit.\n"
        "4) Evaluate each acceptance criterion with reasonable judgment. "
        "Minor issues (date format, label variations, word order) should NOT fail a criterion if the core requirement is met. "
        "Focus on whether the assistant provided semantically correct and useful information.\n"
        "5) Only list unexpected_examples text in unexpected_hits if they represent ACTUAL problems "
        "(e.g., wrong dates, hallucinated content, missing critical info). "
        "Do NOT penalize for reasonable variations or formatting choices.\n"
        "6) Set passed = (expected_hits >= expected_required) AND (most acceptance criteria passed) AND (no serious unexpected_hits).\n"
        "7) Output ONLY a single JSON object with the schema below, no extra text."
    )

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": instructions},
        {"role": "user", "content": "TEST CASE (JSON):\n" + json.dumps(wrapper, ensure_ascii=False, indent=2)},
        {"role": "user", "content": "REQUIRED OUTPUT SCHEMA (describe, not examples):\n" + json.dumps(schema, ensure_ascii=False, indent=2)}
    ]
    return messages

def evaluate_with_llm(llm: LLM, case: dict, payload: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    messages = build_eval_messages(case, payload)
    raw = llm.chat(messages, temperature=0.0)
    data = _json_from_text(raw)
    if not data or not isinstance(data, dict):
        eval_result = {
            "passed": False,
            "expected_hits": 0,
            "expected_required": len(case.get("expected_findings") or []),
            "acceptance_passed": 0,
            "acceptance_total": len(case.get("acceptance_criteria") or []),
            "unexpected_hits": [],
            "notes": [f"LLM palautti ei-JSONin tai virheellisen JSONin: {raw[:200]}..."]
        }
        grading = calculate_test_score(eval_result, cfg)
        eval_result.update(grading)
        return eval_result

    # Normalize to report shape
    acceptance = data.get("acceptance") or []
    acc_passed = sum(1 for a in acceptance if a.get("passed") is True)
    acc_total = len(acceptance)

    eval_result = {
        "passed": bool(data.get("passed")),
        "expected_hits": int(data.get("expected_hits") or 0),
        "expected_required": int(data.get("expected_required") or len(case.get("expected_findings") or [])),
        "acceptance_passed": acc_passed,
        "acceptance_total": acc_total,
        "unexpected_hits": data.get("unexpected_hits") or [],
        "notes": data.get("notes") or [],
        "acceptance_detail": acceptance,
        "raw_evaluator": data,  # keep the full evaluator payload for debugging
    }

    # Calculate graded score
    grading = calculate_test_score(eval_result, cfg)
    eval_result.update(grading)

    return eval_result

# ---------- Testcases over WS ----------

def run_testcases_over_ws(ws_url: str, phone_number: str, testcases_root: Path, llm: LLM, cfg: Dict[str, Any], ws_timeout: int = 60) -> List[Dict[str, Any]]:
    suites = read_all_json_recursive(testcases_root)
    results: List[Dict[str, Any]] = []

    log.info(f"Found {len(suites)} test suite file(s) in {testcases_root}")

    for suite_path in suites:
        try:
            with suite_path.open("r", encoding="utf-8") as f:
                suite = json.load(f)
        except Exception as e:
            log.error(f"Skipping invalid testcase file {suite_path}: {e}")
            continue

        suite_name = suite.get("suite_name", suite_path.name)
        cases = suite.get("cases", [])
        if not isinstance(cases, list):
            log.warning(f"Suite {suite_name} has no 'cases' list; skipping.")
            continue

        log.info(f"Processing suite '{suite_name}' with {len(cases)} test case(s)")

        for case_idx, case in enumerate(cases, 1):
            cid = case.get("id", str(uuid.uuid4()))
            title = case.get("title", "")
            log.info(f"[{case_idx}/{len(cases)}] WS test → Suite: {suite_name} | Case: {cid} - {title}")

            # Connect to WebSocket
            ws = None
            try:
                log.debug(f"Connecting to WebSocket: {ws_url} (timeout={ws_timeout}s)")
                ws = create_connection(ws_url, timeout=ws_timeout)
                log.debug(f"WebSocket connected successfully for case {cid}")
            except Exception as e:
                log.error(f"WS connect failed for case {cid}: {e}")
                results.append({
                    "suite": suite_name, "case_id": cid, "title": title,
                    "transport_ok": False, "ok": False, "error": f"Connection failed: {str(e)}"
                })
                continue

            transport_ok = True
            payload: Dict[str, Any] = {}
            error_msg = None

            try:
                if "prompt_sequence" in case and isinstance(case["prompt_sequence"], list):
                    log.info(f"Executing multi-step test with {len(case['prompt_sequence'])} prompts")
                    all_replies = []
                    for step_idx, step in enumerate(case["prompt_sequence"], 1):
                        log.debug(f"  Step {step_idx}/{len(case['prompt_sequence'])}: Sending prompt (length={len(step)})")
                        ws.send(json.dumps({"message": step, "phone_number": phone_number}))
                        log.debug(f"  Step {step_idx}: Waiting for LLM response...")
                        reply = _receive_llm_response(ws)
                        log.debug(f"  Step {step_idx}: Received LLM response (length={len(reply)})")
                        all_replies.append(reply)
                        time.sleep(0.2)
                    payload = {"replies": all_replies}
                    log.info(f"Multi-step test completed: received {len(all_replies)} replies")
                else:
                    prompt = case.get("prompt", "")
                    log.debug(f"Sending single prompt (length={len(prompt)})")
                    ws.send(json.dumps({"message": prompt, "phone_number": phone_number}))
                    log.debug("Waiting for LLM response...")
                    reply = _receive_llm_response(ws)
                    log.debug(f"Received LLM response (length={len(reply)})")
                    payload = {"reply": reply}
                    log.info(f"Single-step test completed")
            except Exception as e:
                transport_ok = False
                error_msg = f"Transport error: {str(e)}"
                log.error(f"WS communication failed for case {cid}: {e}")
            finally:
                try:
                    if ws:
                        ws.close()
                        log.debug(f"WebSocket closed for case {cid}")
                except Exception as close_err:
                    log.warning(f"Error closing WebSocket for case {cid}: {close_err}")

            # --- Evaluate with LLM
            if not transport_ok or error_msg:
                # Skip evaluation if transport failed
                log.warning(f"Skipping LLM evaluation for case {cid} due to transport error")
                evaluation = {
                    "passed": False,
                    "expected_hits": 0,
                    "expected_required": len(case.get("expected_findings") or []),
                    "acceptance_passed": 0,
                    "acceptance_total": len(case.get("acceptance_criteria") or []),
                    "unexpected_hits": [],
                    "notes": [error_msg or "Transport failed"]
                }
                grading = calculate_test_score(evaluation, cfg)
                evaluation.update(grading)
            else:
                try:
                    log.debug(f"Starting LLM evaluation for case {cid}")
                    evaluation = evaluate_with_llm(llm, case, payload, cfg)
                    log.info(f"LLM evaluation complete for case {cid}: passed={evaluation.get('passed', False)}, score={evaluation.get('score', 0)}")
                except Exception as e:
                    log.error(f"LLM evaluation failed for case {cid}: {e}", exc_info=True)
                    evaluation = {
                        "passed": False,
                        "expected_hits": 0,
                        "expected_required": len(case.get("expected_findings") or []),
                        "acceptance_passed": 0,
                        "acceptance_total": len(case.get("acceptance_criteria") or []),
                        "unexpected_hits": [],
                        "notes": [f"LLM evaluation error: {e}"]
                    }
                    grading = calculate_test_score(evaluation, cfg)
                    evaluation.update(grading)

            result_row = {
                "suite": suite_name,
                "case_id": cid,
                "title": title,
                "transport_ok": transport_ok,
                "ok": evaluation["passed"],           # now 'ok' means evaluation passed
                "evaluation": evaluation,
            }
            if error_msg:
                result_row["error"] = error_msg

            # include replies (truncate to keep file sizes sane)
            if "reply" in payload:
                text = payload["reply"]
                result_row["reply"] = text if len(text) <= 4000 else (text[:4000] + " …[truncated]")
            if "replies" in payload:
                trunc = []
                for r in payload["replies"]:
                    trunc.append(r if len(r) <= 4000 else (r[:4000] + " …[truncated]"))
                result_row["replies"] = trunc

            results.append(result_row)
            log.info(f"Case {cid} result recorded: ok={result_row['ok']}, transport_ok={transport_ok}")

    log.info(f"Completed all test suites: {len(results)} total results")
    return results

# ---------- Reporting ----------

def write_reports(out_dir: Path, report: Dict[str, Any]) -> Tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = out_dir / f"smoke-report-{ts}.json"
    md_path = out_dir / f"smoke-report-{ts}.md"

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    ws = report.get("ws", {})
    rag = report.get("rag", {})
    cleanup = report.get("cleanup", {})

    # Calculate grading statistics
    results = ws.get("results", [])
    total_score = sum(r.get("evaluation", {}).get("score", 0) for r in results)
    avg_score = total_score / len(results) if results else 0

    summary = [
        f"# Smoke Test Report ({ts})",
        "",
        f"**Admin API**: `{report.get('admin_api_base','')}`",
        f"**WS URL**: `{ws.get('url','')}`",
        f"**Company ID**: `{report.get('company_id','')}`",
        f"**User ID**: `{report.get('user_id','')}`",
        "",
        f"- RAG root: `{rag.get('root','')}`",
        f"- RAG docs added: **{rag.get('added',0)}**",
        f"- Test suites total cases: **{ws.get('summary',{}).get('total_cases',0)}**",
        f"- Cases PASSED: **{ws.get('summary',{}).get('ok',0)}**, FAILED: **{ws.get('summary',{}).get('failed',0)}**",
        f"- **Average Score**: {avg_score:.2f}%",
        "",
        "## Test Results Summary",
        "",
    ]

    # Build table with proper column widths
    # Column widths: Case ID(8), Title(45), Score(8), Pass(6), Findings(10), Acceptance(12)
    header = "| Case ID  | Title                                         | Score    | Pass | Findings   | Acceptance   |"
    separator = "|----------|-----------------------------------------------|----------|------|------------|--------------|"
    summary.append(header)
    summary.append(separator)

    for r in results:
        ev = r.get("evaluation", {})
        case_id = r.get("case_id", "").ljust(8)
        title = r.get("title", "")[:45].ljust(45)  # Truncate and pad to 45 chars
        score = f"{ev.get('score', 0):.1f}%".ljust(8)
        passed = ("✅" if ev.get("passed") else "❌").ljust(4)
        findings = f"{ev.get('expected_hits', 0)}/{ev.get('expected_required', 0)}".ljust(10)
        acceptance = f"{ev.get('acceptance_passed', 0)}/{ev.get('acceptance_total', 0)}".ljust(12)
        summary.append(
            f"| {case_id} | {title} | {score} | {passed} | {findings} | {acceptance} |"
        )

    summary.extend([
        "",
        "## Failures & Issues",
        "",
    ])
    failures = [r for r in ws.get("results", []) if not r.get("ok")]
    if not failures:
        summary.append("_None - All tests passed!_")
    else:
        for r in failures:
            ev = r.get("evaluation", {})
            # Get the full note text without truncation
            notes = ev.get("notes", [])
            if isinstance(notes, list):
                first_note = notes[0] if notes else "n/a"
            else:
                first_note = notes if notes else "n/a"

            score = ev.get("score", 0)
            case_id = r.get('case_id', '')

            # Format the failure entry with full note text
            summary.append(f"### {case_id} ({score:.1f}%)")
            summary.append("")
            summary.append(first_note)
            summary.append("")

    summary.extend([
        "## Cleanup",
        f"- Metadata deleted: {cleanup.get('metadata_deleted',0)}",
        f"- User deleted: {cleanup.get('user_deleted',False)}",
        f"- Company deleted: {cleanup.get('company_deleted',False)}",
        "",
        "## Timings",
        f"- Started: {report.get('started_at','')}",
        f"- Finished: {report.get('finished_at','')}",
    ])
    with md_path.open("w", encoding="utf-8") as f:
        f.write("\n".join(summary))

    return json_path, md_path

# ---------- Main flow ----------

def main():
    started_at = _now_iso()

    cfg_path = os.getenv("SMOKE_CONFIG", "config.json")
    cfg = load_config(cfg_path)

    # Output directory (default ./out)
    out_dir = Path(cfg.get("out_dir", "./out"))

    # Read LLM keys from the SAME config file (export to ENV), then init client
    llm_env = apply_llm_env_from_cfg(cfg)
    log.info(
        "Loaded LLM cfg: openai_key=%s, azure_key=%s, azure_endpoint='%s', azure_version='%s'",
        _mask(llm_env["openai_key"]), _mask(llm_env["azure_key"]), llm_env["azure_endpoint"], llm_env["azure_version"]
    )
    llm = LLM(cfg)

    admin_api_base = cfg.get("admin_api_base")
    if not admin_api_base:
        raise RuntimeError("admin_api_base must be set in config")

    admin_username = os.getenv("ADMIN_USERNAME", cfg.get("admin_username", "admin"))
    admin_password = os.environ["ADMIN_PASSWORD"]

    ws_url = cfg.get("ws_url", "ws://localhost:8000/ws")

    company_doc = cfg.get("company", {"name": f"SmokeTestCo-{uuid.uuid4().hex[:6]}"})
    user_doc = cfg.get("user", {
        "first_name": "Smoke",
        "last_name": "Tester",
        "phone_number": "+12025550199",
        "company_id": "",  # set after create_company
        "admin_password": admin_password
    })

    rag_root = Path(cfg.get("rag_root", "./rag"))
    testcases_root = Path(cfg.get("testcases_root", "./testcases"))

    # Placeholders for report
    added = 0
    results: List[Dict[str, Any]] = []
    company_id = ""
    user_id = ""
    cleanup_info = {"metadata_deleted": 0, "user_deleted": False, "company_deleted": False}

    try:
        # --- Admin login
        log.info("Logging in as admin…")
        admin_token = login_admin(admin_api_base, admin_username, admin_password)

        # --- Create company
        log.info("Creating test company…")
        company_id = create_company(admin_api_base, admin_token, company_doc)
        log.info(f"Company created: {company_id}")

        # --- Create user
        user_doc = dict(user_doc)
        user_doc["company_id"] = company_id
        log.info("Creating test user…")
        user_id = create_user(admin_api_base, admin_token, user_doc)
        log.info(f"User created: {user_id}")

        # --- Ingest RAG JSON files
        if rag_root.exists():
            log.info(f"Ingesting RAG JSONs from {rag_root.resolve()} …")
            rag_docs = load_rag_docs(rag_root)
            log.info(f"Loaded {len(rag_docs)} RAG documents to ingest")

            # Track document IDs for polling
            inserted_doc_ids = []

            for idx, (meta, rel) in enumerate(rag_docs, 1):
                log.debug(f"Ingesting RAG doc {idx}/{len(rag_docs)}: {rel}")
                meta_doc = dict(meta)
                meta_doc["company_id"] = company_id
                try:
                    meta_id = add_metadata(admin_api_base, admin_token, meta_doc)
                    inserted_doc_ids.append(meta_id)
                    added += 1
                    log.debug(f"Successfully added metadata {meta_id} for {rel}")
                except Exception as e:
                    log.error(f"Failed to add metadata for {rel}: {e}")
            log.info(f"RAG metadata added: {added}")

            # Wait for RAG insertion to complete
            if inserted_doc_ids:
                log.info(f"Waiting for {len(inserted_doc_ids)} documents to be inserted into RAG system...")
                rag_timeout = int(cfg.get("RAG_TIMEOUT_SECONDS", 300))  # Default 5 minutes
                rag_poll_interval = int(cfg.get("RAG_POLL_INTERVAL_SECONDS", 5))  # Default 5 seconds

                success = wait_for_rag_insertion(
                    admin_api_base,
                    admin_token,
                    company_id,
                    inserted_doc_ids,
                    timeout=rag_timeout,
                    poll_interval=rag_poll_interval
                )

                if not success:
                    log.error("RAG insertion did not complete within timeout. Tests may fail.")
                else:
                    log.info("All RAG documents successfully inserted. Ready for testing.")
        else:
            log.warning(f"RAG root not found: {rag_root.resolve()}")

        # --- Login as user (phone + admin_password)
        log.info("Logging in as user…")
        r = requests.post(api(admin_api_base, "/login"),
                          json={"username": user_doc["phone_number"], "password": admin_password},
                          timeout=20)
        r.raise_for_status()
        _user_token = r.json()["token"]
        log.info("User login OK.")

        # --- Run testcases via WS and evaluate with LLM
        if testcases_root.exists():
            ws_timeout = int(cfg.get("WS_TIMEOUT_SECONDS", 60))
            log.info(f"Starting WebSocket test execution (timeout={ws_timeout}s per operation)")
            try:
                results = run_testcases_over_ws(ws_url, user_doc["phone_number"], testcases_root, llm, cfg, ws_timeout)
                ok_count = sum(1 for r in results if r.get("ok"))
                log.info(f"WS tests evaluated by LLM. {ok_count}/{len(results)} passed.")
            except Exception as e:
                log.error(f"WebSocket test execution failed: {e}", exc_info=True)
                # If we have partial results, keep them
                if results:
                    log.warning(f"Preserving {len(results)} partial results before error occurred")
                else:
                    log.error("No results collected before error")
                # Re-raise to trigger cleanup but preserve what we have
                raise
        else:
            log.warning(f"Testcases root not found: {testcases_root.resolve()}")

    finally:
        # --- Cleanup (best-effort, but tracked for report)
        try:
            if company_id:
                log.info("Cleaning up created metadata…")
                cleanup_info["metadata_deleted"] = delete_company_metadata_bulk(admin_api_base, admin_token, company_id)
                log.info(f"Deleted metadata docs: {cleanup_info['metadata_deleted']}")
        except Exception as e:
            log.warning(f"Cleanup (metadata) failed: {e}")

        try:
            if user_id:
                log.info("Deleting user…")
                delete_user(admin_api_base, admin_token, user_id)
                cleanup_info["user_deleted"] = True
        except Exception as e:
            log.warning(f"Cleanup (user) failed: {e}")

        try:
            if company_id:
                log.info("Deleting company…")
                delete_company(admin_api_base, admin_token, company_id)
                cleanup_info["company_deleted"] = True
        except Exception as e:
            log.warning(f"Cleanup (company) failed: {e}")

        finished_at = _now_iso()

        # --- Build report dict and write files
        report: Dict[str, Any] = {
            "started_at": started_at,
            "finished_at": finished_at,
            "admin_api_base": admin_api_base,
            "ws": {
                "url": ws_url,
                "results": results,
                "summary": {
                    "total_cases": len(results),
                    "ok": sum(1 for r in results if r.get("ok")),
                    "failed": sum(1 for r in results if not r.get("ok")),
                }
            },
            "rag": {
                "root": str(rag_root.resolve()),
                "added": added
            },
            "company_id": company_id,
            "user_id": user_id,
            "cleanup": cleanup_info,
            "config_snapshot": {
                "out_dir": str(out_dir.resolve()),
                "rag_root": str(rag_root.resolve()),
                "testcases_root": str(testcases_root.resolve()),
                "llm": {
                    "provider": "azure" if (os.getenv("AZURE_API_KEY") and os.getenv("AZURE_ENDPOINT")) else "openai",
                    "model": cfg.get("GPT_CHAT_MODEL") or cfg.get("gpt_model") or "gpt-4o-mini",
                    "openai_key": _mask(os.environ.get("OPENAI_API_KEY")),
                    "azure_key": _mask(os.environ.get("AZURE_API_KEY")),
                    "azure_endpoint": os.environ.get("AZURE_ENDPOINT", ""),
                    "azure_version": os.environ.get("AZURE_VERSION", "")
                }
            }
        }

        json_path, md_path = write_reports(out_dir, report)
        log.info(f"Report written: {json_path}")
        log.info(f"Summary written: {md_path}")
        log.info("Done.")

if __name__ == "__main__":
    main()
