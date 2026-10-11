"""Long-term breast cancer risk profile (Dr7.ai gateway / MedGemma).

This is an EDUCATIONAL layer, separate from both Wassim's outcome model and the action policy:
  * it never changes the recommended action, priority, booking eligibility or tasks;
  * it describes long-term statistical risk factors only, never current disease;
  * it only ever sees a de-identified, allow-listed payload (see sanitize.py).

Backends (HEALTHIES_RISK_BACKEND): off | fixture | dr7
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from pydantic import ValidationError

from .. import config
from .prompt import PROMPT_VERSION, build_messages
from .sanitize import PIIViolation, sanitized_payload
from .schema import MAX_ITEM_CHARS, MAX_ITEMS, RiskProfile

log = logging.getLogger("healthies.risk")

# Output guard: statements the profile must never make. Items matching are dropped.
_FORBIDDEN = [
    r"\byou (do not|don't) have (breast )?cancer\b", r"\bcancer[- ]free\b", r"\bno (need|reason) (for|to) (be )?screen",
    r"\b(you|she) (have|has|likely has) (breast )?cancer\b", r"\bdiagnos(is|ed|e) (of|with) cancer\b",
    r"\d+(\.\d+)?\s?%",
    "لا تحتاجين", "لا يوجد لديك سرطان", "ليس لديك سرطان",
]
_FORBIDDEN_RE = [re.compile(p, re.I) for p in _FORBIDDEN]


@dataclass
class RiskResult:
    status: str                      # ok | disabled | unavailable | error | blocked_pii
    backend: str
    model: Optional[str] = None
    profile: Optional[RiskProfile] = None
    mode: Optional[str] = None       # parse | json_fallback | fixture
    payload: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    is_fixture: bool = False
    dropped_items: list[str] = field(default_factory=list)


def _guard(profile: RiskProfile) -> tuple[RiskProfile, list[str]]:
    """Trim, cap and remove any item that crosses into diagnosis or false reassurance."""
    dropped: list[str] = []

    def clean(items: list[str]) -> list[str]:
        out = []
        for it in items:
            it = " ".join(str(it).split())[:MAX_ITEM_CHARS]
            if not it:
                continue
            if any(r.search(it) for r in _FORBIDDEN_RE):
                dropped.append(it)
                continue
            out.append(it)
        return out[:MAX_ITEMS]

    return RiskProfile(
        estimated_risk_tier=profile.estimated_risk_tier,
        non_modifiable_historical_factors=clean(profile.non_modifiable_historical_factors),
        modifiable_lifestyle_factors=clean(profile.modifiable_lifestyle_factors),
        clinical_screening_recommendations=clean(profile.clinical_screening_recommendations),
    ), dropped


# ------------------------------------------------------------------------- fixture -----
def _fixture(payload: dict[str, Any], language: str) -> RiskProfile:
    """Deterministic demo output so the UI works offline. Clearly labelled as demo in the UI."""
    f = payload["factors"]
    ar = language == "ar"
    hist, life, recs = [], [], []
    points = 0
    if f.get("personal_history") == "Yes":
        points += 3
        hist.append("إصابة سابقة بسرطان الثدي." if ar else "A previous breast cancer diagnosis.")
    if f.get("surveillance_plan") == "Yes":
        points += 3
        hist.append("خطة فحص خاصة أوصى بها طبيب (مثلًا بسبب نتيجة جينية)." if ar else "A doctor-advised special check plan (for example a gene result).")
    fam = sum(f.get(k) == "Yes" for k in ("family_maternal", "family_paternal"))
    if fam:
        points += fam
        hist.append(("وجود قريبة أو أكثر مصابة بسرطان الثدي أو المبيض." if ar else
                     "One or more relatives with breast or ovarian cancer."))
    band = f.get("age_band_years", "unknown")
    if band != "unknown" and int(band.split("-")[0]) >= 50:
        hist.append("يرتفع الخطر مع التقدّم في العمر." if ar else "Risk rises with age.")
    if f.get("menarche") == "Younger than 12":
        points += 0.5
        hist.append("بدء الدورة الشهرية قبل سن 12." if ar else "First period before age 12.")
    if f.get("first_birth") in ("I have not given birth", "30 or older"):
        points += 0.5
        hist.append("عدم الإنجاب أو أول ولادة بعد سن 30." if ar else "No births, or first birth at 30 or older.")
    if f.get("dense_breasts") == "Yes":
        points += 1
        hist.append("أنسجة ثدي كثيفة بحسب الطبيب." if ar else "Dense breast tissue reported by a doctor.")
    if f.get("hormone_therapy") == "Yes, I take it now":
        points += 0.5
        life.append("العلاج الهرموني الحالي لانقطاع الطمث؛ ناقشي مدّته مع طبيبكِ." if ar else "Current menopausal hormone therapy; review its duration with your doctor.")
    alc = f.get("alcohol", "")
    if alc in ("1 to 6 drinks a week", "7 or more drinks a week"):
        points += 0.5
        life.append("شرب الكحول؛ التقليل منه يخفّض الخطر." if ar else "Drinking alcohol; less alcohol lowers risk.")
    if f.get("activity") in ("Rarely or never", "1 or 2 days"):
        life.append("قلّة النشاط البدني؛ يساعد النشاط المنتظم على خفض الخطر." if ar else "Low physical activity; regular activity helps lower risk.")
    if f.get("smoking", "").startswith("Yes, I smoke"):
        life.append("التدخين (بما فيه النرجيلة)؛ الإقلاع مفيد للصحة عمومًا." if ar else "Smoking (including argileh); stopping benefits overall health.")
    if f.get("weight") == "Yes":
        life.append("زيادة الوزن بعد انقطاع الطمث." if ar else "Weight gain after menopause.")

    major = fam + 3 * (f.get("personal_history") == "Yes") + 3 * (f.get("surveillance_plan") == "Yes")
    minor = points - major
    tier = ("High" if major >= 2 else "Moderate" if major >= 1 or minor >= 1.5
            else "Average" if minor > 0 or hist else "Low")
    recs.append("اتّبعي برنامج الكشف بالماموغرام المناسب لعمركِ بحسب الإرشادات الوطنية." if ar else
                "Follow mammography screening for your age group as advised by national guidance.")
    if fam >= 1 or f.get("surveillance_plan") == "Yes":
        recs.append("ناقشي مع طبيبكِ ما إذا كانت الاستشارة الوراثية مناسبة لكِ." if ar else
                    "Ask a clinician whether genetic counselling is appropriate for you.")
    if life:
        recs.append("ناقشي مع طبيبكِ عادات نمط الحياة التي يمكن تحسينها." if ar else
                    "Discuss the lifestyle factors above with a clinician or nurse.")
    if f.get("symptoms") not in ("None of these", "unknown", None):
        recs.insert(0, "يجب أن يفحص طبيب التغيّر الذي ذكرتِه؛ يتابع فريق الرعاية ذلك." if ar else
                    "Have the change you reported checked by a clinician; your care team is arranging this.")
    return RiskProfile(estimated_risk_tier=tier, non_modifiable_historical_factors=hist,
                       modifiable_lifestyle_factors=life, clinical_screening_recommendations=recs)


# ------------------------------------------------------------------------- Dr7.ai ------
def _client():
    from openai import OpenAI  # imported lazily so the app runs without the SDK in fixture mode

    return OpenAI(api_key=config.DR7_API_KEY, base_url=config.DR7_BASE_URL,
                  timeout=config.DR7_TIMEOUT_SECONDS, max_retries=1)


def _parse_call(client, messages):
    """OpenAI SDK structured outputs: strict JSON schema derived from RiskProfile."""
    completions = client.chat.completions
    parse = getattr(completions, "parse", None) or client.beta.chat.completions.parse  # SDK 1.x fallback
    resp = parse(model=config.DR7_MODEL, messages=messages, response_format=RiskProfile, temperature=0.1)
    msg = resp.choices[0].message
    if getattr(msg, "refusal", None):
        raise ValueError(f"Model refused: {msg.refusal}")
    if msg.parsed is None:
        raise ValueError("Model returned no parsed object.")
    return msg.parsed


def _json_fallback_call(client, messages):
    """For gateways that ignore or reject response_format: same schema, validated locally."""
    resp = client.chat.completions.create(model=config.DR7_MODEL, messages=messages, temperature=0.1, max_tokens=900)
    text = (resp.choices[0].message.content or "").strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("Model reply contained no JSON object.")
    return RiskProfile.model_validate(json.loads(m.group(0)))


def _dr7(payload: dict[str, Any], language: str) -> tuple[RiskProfile, str]:
    if not config.DR7_API_KEY:
        raise ConnectionError("DR7_API_KEY is not set.")
    client = _client()
    try:
        return _parse_call(client, build_messages(payload, language)), "parse"
    except Exception as exc:  # noqa: BLE001
        if config.DR7_STRUCTURED_MODE == "parse":
            raise
        cls = type(exc).__name__
        if cls in {"AuthenticationError", "PermissionDeniedError", "RateLimitError", "APIConnectionError", "APITimeoutError"}:
            raise
        log.info("Structured parse unavailable (%s: %s); using validated JSON fallback.", cls, exc)
        return _json_fallback_call(client, build_messages(payload, language, json_fallback=True)), "json_fallback"


# ------------------------------------------------------------------------- entry -------
def generate_risk_profile(answers: dict[str, Any], participant: Any, language: str = "en",
                          backend: Optional[str] = None) -> RiskResult:
    """Never raises. Any failure is returned as a status the UI can show honestly."""
    name = (backend or config.RISK_BACKEND).lower()
    if name == "off":
        return RiskResult(status="disabled", backend=name)
    try:
        payload = sanitized_payload(answers, participant)
    except PIIViolation as exc:
        log.warning("Risk profile blocked: %s", exc)
        return RiskResult(status="blocked_pii", backend=name, error=str(exc))
    try:
        if name == "fixture":
            profile, mode, model = _fixture(payload, language), "fixture", "fixture-risk-0 (demo)"
        elif name == "dr7":
            profile, mode = _dr7(payload, language)
            model = config.DR7_MODEL
        else:
            return RiskResult(status="error", backend=name, error=f"Unknown risk backend '{name}'.")
        profile, dropped = _guard(profile)
        return RiskResult(status="ok", backend=name, model=model, profile=profile, mode=mode, payload=payload,
                          is_fixture=name == "fixture", dropped_items=dropped)
    except (ConnectionError, TimeoutError) as exc:
        return RiskResult(status="unavailable", backend=name, payload=payload, error=str(exc))
    except (ValidationError, ValueError, json.JSONDecodeError) as exc:
        return RiskResult(status="error", backend=name, payload=payload, error=f"Invalid model output: {exc}"[:500])
    except Exception as exc:  # noqa: BLE001 - network/SDK errors must not break the care journey
        cls = type(exc).__name__
        status = "unavailable" if cls in {"APIConnectionError", "APITimeoutError", "RateLimitError", "InternalServerError"} else "error"
        log.exception("Risk profile call failed")
        return RiskResult(status=status, backend=name, payload=payload, error=f"{cls}: {exc}"[:500])


__all__ = ["generate_risk_profile", "RiskResult", "PROMPT_VERSION"]
