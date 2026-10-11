"""Central configuration. Everything here can be overridden with environment variables
(or a `.env`-style export before starting the server)."""
from __future__ import annotations

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent
DATA_DIR = Path(__file__).resolve().parent / "data"

DATABASE_URL = os.getenv("HEALTHIES_DATABASE_URL", f"sqlite:///{BACKEND_DIR / 'healthies.db'}")

# ---- Model integration -------------------------------------------------------
# "fixture"  : labelled demo responses (default until Wassim's model is ready)
# "python"   : import model/inference.py and call predict(request_dict)
# "sklearn"  : load model/fitted_pipeline.joblib + model/model_config.json
# "http"     : POST the request to HEALTHIES_MODEL_URL
MODEL_BACKEND = os.getenv("HEALTHIES_MODEL_BACKEND", "fixture").lower()
MODEL_DIR = Path(os.getenv("HEALTHIES_MODEL_DIR", PROJECT_DIR / "model"))
MODEL_URL = os.getenv("HEALTHIES_MODEL_URL", "http://127.0.0.1:9000/predict")
MODEL_TIMEOUT_SECONDS = float(os.getenv("HEALTHIES_MODEL_TIMEOUT", "5"))

CONTRACT_VERSION = "1.0"

# ---- Files the content team edits -------------------------------------------
SURVEY_FILE = Path(os.getenv("HEALTHIES_SURVEY_FILE", DATA_DIR / "survey.json"))
POLICY_FILE = Path(os.getenv("HEALTHIES_POLICY_FILE", DATA_DIR / "policy_config.json"))
HOSPITALS_FILE = Path(os.getenv("HEALTHIES_HOSPITALS_FILE", DATA_DIR / "hospitals.json"))
OUTREACH_FILE = Path(os.getenv("HEALTHIES_OUTREACH_FILE", DATA_DIR / "outreach_templates.json"))

FRONTEND_DIST = Path(os.getenv("HEALTHIES_FRONTEND_DIST", PROJECT_DIR / "frontend" / "dist"))

SESSION_HOURS = int(os.getenv("HEALTHIES_SESSION_HOURS", "12"))
DEMO_PASSWORD = os.getenv("HEALTHIES_DEMO_PASSWORD", "demo1234")

# Demo controls (reset / advance time / simulate outage). Set to 0 for anything beyond a demo.
DEMO_MODE = os.getenv("HEALTHIES_DEMO_MODE", "1") == "1"

# ---- Long-term risk profile (LLM via Dr7.ai gateway) -------------------------------
# "off"     : feature hidden
# "fixture" : deterministic, clearly-labelled demo profile (no network, default)
# "dr7"     : call the Dr7.ai OpenAI-compatible gateway with a de-identified payload
RISK_BACKEND = os.getenv("HEALTHIES_RISK_BACKEND", "fixture").lower()
DR7_API_KEY = os.getenv("DR7_API_KEY", "")
# Dr7.ai docs (Oct 2026) show POST https://dr7.ai/api/v1/medical/chat/completions; the OpenAI SDK
# appends "/chat/completions" to this base URL. Override if your dashboard shows another one.
DR7_BASE_URL = os.getenv("DR7_BASE_URL", "https://dr7.ai/api/v1/medical")
DR7_MODEL = os.getenv("DR7_MODEL", "medgemma-4b-it")
DR7_TIMEOUT_SECONDS = float(os.getenv("DR7_TIMEOUT", "45"))
# "auto": try .parse() with a strict JSON schema, fall back to JSON-in-text validated against the
# same schema if the gateway rejects response_format. "parse": structured outputs only.
DR7_STRUCTURED_MODE = os.getenv("DR7_STRUCTURED_MODE", "auto").lower()
