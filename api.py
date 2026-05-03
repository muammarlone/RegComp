"""RegComp — Regulatory Compliance Agent.

Endpoints:
  GET  /health
  POST /api/v1/compliance/assess     — SVAS compliance assessment
  GET  /api/v1/compliance/frameworks — list supported regulatory frameworks
  GET  /api/v1/compliance/history    — past assessments

LLM: OpenRouter (OPENROUTER_API_KEY). Mock fallback when key absent.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import urllib.error
import urllib.request
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logger = logging.getLogger("RegComp")
logging.basicConfig(level=logging.INFO)

_DB         = os.getenv("REGCOMP_DB_PATH", "regcomp.db")
_OR_KEY     = os.getenv("OPENROUTER_API_KEY", "")
_OR_BASE    = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
_OR_MODEL   = os.getenv("OPENROUTER_MODEL", "anthropic/claude-3.5-haiku")

_SYSTEM_PROMPT = """You are RegComp, an expert regulatory compliance analyst.
Given an intent, produce a compliance assessment in JSON:
{
  "frameworks": ["GDPR", "HIPAA", ...],
  "gap_count": 3,
  "gaps": [{"control": "...", "severity": "HIGH|MED|LOW", "remediation": "..."}],
  "compliance_score": 72,
  "summary": "...",
  "next_steps": ["...", "..."]
}
Respond with valid JSON only. No markdown. Be specific to the stated domain."""

_FRAMEWORKS = [
    "GDPR", "HIPAA", "SOX", "PCI DSS", "ISO 27001", "SOC 2",
    "NIST CSF", "CCPA", "DORA", "NIS2", "FedRAMP",
]


def _init_db():
    conn = sqlite3.connect(_DB)
    conn.execute("""CREATE TABLE IF NOT EXISTS assessments (
        id TEXT PRIMARY KEY, workflow_id TEXT, intent TEXT,
        frameworks TEXT, score REAL, gap_count INTEGER,
        summary TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    conn.close()


def _call_or(intent: str) -> dict:
    payload = json.dumps({
        "model": _OR_MODEL, "max_tokens": 1024,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": f"Intent: {intent}"},
        ],
    }).encode()
    req = urllib.request.Request(
        f"{_OR_BASE}/chat/completions", data=payload,
        headers={"Authorization": f"Bearer {_OR_KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode())
    return json.loads(body["choices"][0]["message"]["content"].strip())


def _mock(intent: str) -> dict:
    return {
        "frameworks": ["GDPR", "ISO 27001"],
        "gap_count": 2,
        "gaps": [
            {"control": "Data Subject Rights", "severity": "HIGH",
             "remediation": "Implement DSAR workflow within 30 days"},
            {"control": "Audit Logging", "severity": "MED",
             "remediation": "Enable immutable audit trail for all data access"},
        ],
        "compliance_score": 74,
        "summary": f"Compliance assessment for: {intent[:120]}. Two gaps identified.",
        "next_steps": ["Conduct DPA for new processing activities",
                       "Schedule quarterly compliance review"],
    }


@asynccontextmanager
async def _lifespan(app: FastAPI):
    _init_db()
    yield


app = FastAPI(title="RegComp", version="1.0.0", lifespan=_lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])


class AssessRequest(BaseModel):
    intent: str
    workflow_id: str = ""
    context: dict = {}
    frameworks: Optional[list[str]] = None


@app.get("/health")
def health():
    return {"status": "healthy", "service": "RegComp", "llm_available": bool(_OR_KEY)}


@app.post("/api/v1/compliance/assess")
def assess(req: AssessRequest):
    aid = hashlib.sha256(f"{req.workflow_id}:{req.intent}".encode()).hexdigest()[:12]
    source = "openrouter"
    if _OR_KEY:
        try:
            data = _call_or(req.intent)
        except Exception as exc:
            logger.warning("OR failed (%s) — mock", exc)
            data = _mock(req.intent); source = "mock"
    else:
        data = _mock(req.intent); source = "mock"

    conn = sqlite3.connect(_DB)
    conn.execute("INSERT OR IGNORE INTO assessments (id, workflow_id, intent, frameworks, score, gap_count, summary) VALUES (?,?,?,?,?,?,?)",
                 (aid, req.workflow_id, req.intent[:200],
                  json.dumps(data.get("frameworks", [])),
                  data.get("compliance_score", 0),
                  data.get("gap_count", 0),
                  data.get("summary", "")[:300]))
    conn.commit(); conn.close()

    logger.info("Compliance assess: id=%s workflow=%s score=%s", aid, req.workflow_id, data.get("compliance_score"))
    return {"assessment_id": aid, "workflow_id": req.workflow_id,
            "source": source, **data}


@app.get("/api/v1/compliance/frameworks")
def frameworks():
    return {"frameworks": _FRAMEWORKS, "count": len(_FRAMEWORKS)}


@app.get("/api/v1/compliance/history")
def history(limit: int = 50):
    conn = sqlite3.connect(_DB); conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(
        "SELECT id, workflow_id, intent, score, gap_count, created_at FROM assessments ORDER BY created_at DESC LIMIT ?",
        (limit,)).fetchall()]
    conn.close()
    return {"assessments": rows, "count": len(rows)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8011")))
