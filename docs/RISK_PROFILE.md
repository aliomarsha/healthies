# Long-term risk profile (Dr7.ai / MedGemma)

An **educational** layer that describes a participant's long-term statistical breast cancer risk factors, in the style of Gail or Tyrer-Cuzick. It is kept separate from the rest of the platform:

| | Outcome model (Wassim) | Action policy | **Risk profile (this)** |
|---|---|---|---|
| Question it answers | dataset-defined outcome score | what she should do next | which long-term factors raise or lower her risk |
| Changes next step, priority or tasks? | can add clinician review | **yes** | **never** |
| Sees | model features | answers | de-identified, allow-listed answers |

## How it works

1. She submits the assessment. The recommendation is saved and returned immediately.
2. A `risk_profiles` record is created with status `pending`, and a background task runs it. A slow or failing model cannot delay or change her result.
3. **De-identification** (`app/risk/sanitize.py`):
   - **Allow-list:** only approved survey answers are read. Name, phone, code, assessment ID, governorate, barriers, free text and dates are never read.
   - **Generalise:** exact age becomes a 5-year band, and answers become plain-English labels.
   - **Scrub:** every outgoing string is regex-scrubbed for emails, phone numbers, `HL-`/`AS-` IDs and dates.
   - **Gate:** the final payload is checked against her name parts, code and phone digits. Any match **blocks the call** (status `blocked_pii`). Nothing is sent "best effort".
4. **Prompt** (`app/risk/prompt.py`, version `risk-prompt-v1`):
   - Asks for long-term epidemiological risk only, and forbids diagnosing current disease.
   - Forbids "you don't have cancer" or "no screening needed", and forbids percentages.
   - Tells the model to treat `unknown` as missing, not "no".
   - Says symptoms are handled separately by the care team.
   - Asks for the answer in her language (Arabic or English).
5. **Structured output** (`app/risk/service.py`):
   - Calls `client.chat.completions.parse(..., response_format=RiskProfile)` through the OpenAI SDK, with a strict schema built from the Pydantic model in `app/risk/schema.py`. It falls back to `client.beta.chat.completions.parse` on older SDKs.
   - In `DR7_STRUCTURED_MODE=auto` (the default), if the gateway rejects `response_format`, it asks for JSON in plain text and validates it against **the same** `RiskProfile` model. If that also fails, the status is `error` and nothing is shown.
   - `DR7_STRUCTURED_MODE=parse` disables this fallback.
6. **Output guard:** items are trimmed and capped at 6 per list and 240 characters each. Any item that states or implies a diagnosis, reassurance or a percentage is dropped and logged as `dropped_items` for staff.
7. The result is stored with backend, model, mode, prompt version and the exact de-identified payload sent. Programme and hospital staff can see all of this; the participant sees only the tier and the three lists.

Response shape (enforced):

```json
{
  "estimated_risk_tier": "Low | Average | Moderate | High",
  "non_modifiable_historical_factors": ["..."],
  "modifiable_lifestyle_factors": ["..."],
  "clinical_screening_recommendations": ["..."]
}
```

## Turn it on

The default is `fixture`: deterministic demo output, labelled "Demo summary" in the interface, with no network calls.

PowerShell:

```powershell
$env:HEALTHIES_RISK_BACKEND = "dr7"
$env:DR7_API_KEY = "sk-dr7-..."                 # never put this in frontend code or git
# optional, only if your Dr7 dashboard shows different values:
# $env:DR7_BASE_URL = "https://dr7.ai/api/v1/medical"
# $env:DR7_MODEL    = "medgemma-4b-it"
cd backend
python scripts\check_dr7.py                     # live test with a fictional person (English and Arabic)
python -m uvicorn app.main:app --port 8000
```

On macOS or Linux, use `export VAR=value` instead.

| Variable | Default | Meaning |
|---|---|---|
| `HEALTHIES_RISK_BACKEND` | `fixture` | `off`, `fixture` or `dr7` |
| `DR7_API_KEY` | (none) | Your Dr7.ai key. Missing means status `unavailable` |
| `DR7_BASE_URL` | `https://dr7.ai/api/v1/medical` | The SDK appends `/chat/completions` |
| `DR7_MODEL` | `medgemma-4b-it` | Use the exact ID from your Dr7 dashboard |
| `DR7_TIMEOUT` | `45` | Timeout in seconds |
| `DR7_STRUCTURED_MODE` | `auto` | `auto` (parse, then validated JSON) or `parse` only |

Profiles for the seeded people are generated with the fixture. On the programme record page, **Regenerate risk profile** re-runs a profile with the configured backend. Use it after setting the key.

## Notes on Dr7.ai

As of October 2026, Dr7.ai's public docs show the request `POST https://dr7.ai/api/v1/medical/chat/completions` with model `medgemma-4b-it`. Their access page also shows `https://api.dr7.ai/v1` with `medgemma-27b`. They do **not** document `response_format` / JSON-schema support, which is why the validated-JSON fallback exists.

If your dashboard lists a "MedGemma 1.5 4B" ID, set it in `DR7_MODEL`. Run `scripts/check_dr7.py` first: it prints which mode worked (`parse` or `json_fallback`).

## Before using real participant data

- De-identification lowers the risk but does not remove it. Health answers still leave your server.
- You need consent text that covers external AI processing and a data agreement with the provider.
- The output also needs clinical review before it is shown as anything more than general information.
- With fictional demo data, none of this is a concern.
