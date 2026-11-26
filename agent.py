import os
import re
import json
import requests
from pathlib import Path
from typing import Dict, Any, Tuple, Optional
from dotenv import load_dotenv
import database

load_dotenv()

# ── Load FAQ from local file ───────────────────────────────────────────────────

_FAQ_PATH = Path(__file__).parent / "faq.json"

def _load_faq() -> list:
    try:
        with open(_FAQ_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

FAQ_ENTRIES = _load_faq()

# ── Mock calendar slots ────────────────────────────────────────────────────────

MOCK_AVAILABLE_SLOTS = [
    "Tomorrow at 10:00 AM",
    "Tomorrow at 2:30 PM",
    "Friday at 11:00 AM",
    "Monday at 4:00 PM",
]

# ── Qualification field order (one at a time) ──────────────────────────────────
# (field_key, follow-up question to ask when this field is missing)
QUAL_FIELDS = [
    ("name",     "May I start with your name?"),
    ("company",  "Great — which company are you with?"),
    ("role",     "And what is your role or job title there?"),
    ("need",     "What business challenge or workflow are you hoping to solve with voice AI?"),
    ("budget",   "Do you have a rough budget or investment range in mind?"),
    ("timeline", "What is your expected timeline or start date for a solution like this?"),
    ("email",    "Could I grab a contact email so we can send you follow-up details?"),
]

EMPTY = "Not provided"

# ── Groq check ────────────────────────────────────────────────────────────────

def _get_groq_key() -> str:
    return (os.getenv("GROQ_API_KEY") or os.getenv("GROK_API_KEY") or "").strip()

def check_groq_available() -> bool:
    key = _get_groq_key()
    return bool(key and not key.startswith("your_") and len(key) > 10)

# ── FAQ lookup (keyword matching) ─────────────────────────────────────────────

def find_faq(text: str) -> Optional[Dict]:
    """
    Return the best-matching FAQ entry dict, or None.
    Score = number of distinct keyword hits found in lowercased user text.
    Returns None if zero keywords matched (no invented answers).
    """
    lower = text.lower()
    best_score, best_entry = 0, None
    for entry in FAQ_ENTRIES:
        score = sum(1 for kw in entry["keywords"] if kw in lower)
        if score > best_score:
            best_score, best_entry = score, entry
    return best_entry if best_score > 0 else None

# ── Sentiment (keyword rules, labelled as basic estimate) ─────────────────────

_POS_WORDS = {
    "great", "excellent", "perfect", "love", "fantastic", "amazing", "awesome",
    "good", "nice", "interested", "definitely", "absolutely", "yes", "sure",
    "helpful", "impressed", "happy", "excited", "wonderful", "superb", "brilliant",
    "glad", "thank", "thanks", "appreciate", "ideal", "exactly",
}
_NEG_WORDS = {
    "no", "not", "never", "bad", "terrible", "awful", "hate", "dislike",
    "expensive", "costly", "overpriced", "difficult", "hard", "complicated",
    "confused", "annoyed", "frustrated", "disappointed", "wrong", "useless",
    "stop", "cancel", "unsubscribe", "quit", "refuse", "reject", "doubt",
}

def classify_sentiment(text: str) -> str:
    """
    Basic estimate — keyword counting only, not ML-based.
    Returns 'positive', 'negative', or 'neutral'.
    """
    tokens = set(re.findall(r"[a-z]+", text.lower()))
    pos = len(tokens & _POS_WORDS)
    neg = len(tokens & _NEG_WORDS)
    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"

# ── Info extraction helpers ───────────────────────────────────────────────────

def _is_empty(lead: Dict, field: str) -> bool:
    val = lead.get(field, EMPTY)
    return not val or str(val).strip().lower() in (EMPTY.lower(), "", "none", "null")

def _extract_fields(text: str, lead: Dict) -> Dict:
    """
    Try to extract any lead fields mentioned inline.
    Only overwrites fields that are still EMPTY so we never lose captured data.
    """
    lower = text.lower()

    # Name
    if _is_empty(lead, "name"):
        m = re.search(
            r"(?:my name is|i am|i'm|this is)\s+(?!work(?:ing)?\s+(?:at|for|as)\b|looking\b|trying\b|from\b|at\b|with\b)([A-Za-z]+(?:\s+(?!from\b|at\b|with\b|and\b|for\b)[A-Za-z]+)?)",
            text, re.IGNORECASE
        )
        if m:
            lead["name"] = m.group(1).strip().title()

    # Company
    if _is_empty(lead, "company"):
        m = re.search(
            r"(?:from|work(?:ing)?\s+(?:at|for)|at|company is|with)\s+([A-Za-z0-9&.\-\s]{2,30})",
            text, re.IGNORECASE
        )
        if m:
            cand = re.split(r"[,.\n]| and | we | i | as ", m.group(1), flags=re.IGNORECASE)[0].strip()
            if cand.lower() not in ("home", "office", "here", "there", "us", "the"):
                lead["company"] = cand

    # Role: "I'm a VP of Sales", "my role is Head of Operations"
    if _is_empty(lead, "role"):
        m = re.search(
            r"(?:i(?:'m| am)(?: a| the| an)?|my role is|my title is|work(?:ing)? as(?: a| an)?)\s+"
            r"(?!work(?:ing)?\s+(?:at|for)\b|from\b|at\b|with\b)([A-Za-z][A-Za-z\s]{2,40}?)(?:\s+(?:at|for|in)\b|$|[,.])",
            text, re.IGNORECASE
        )
        if m:
            role_cand = m.group(1).strip()
            if 1 <= len(role_cand.split()) <= 6:
                lead["role"] = role_cand.title()

    # Email
    if _is_empty(lead, "email"):
        m = re.search(r"[\w.\-]+@[\w.\-]+\.\w{2,}", text)
        if m:
            lead["email"] = m.group(0)

    # Budget
    if _is_empty(lead, "budget"):
        m = re.search(r"\$[\d,k]+(?:\s*(?:per month|\/mo|monthly|a month|k))?", text, re.IGNORECASE)
        if m:
            lead["budget"] = m.group(0)
        elif any(w in lower for w in ["budget", "spend", "invest", "affordable", "around", "under", "within"]):
            lead["budget"] = text.strip()[:120]  # cap length

    # Timeline
    if _is_empty(lead, "timeline"):
        m = re.search(
            r"\b(\d+\s*(?:week|month|quarter|year)s?|q[1-4]\s*\d{4}|next\s+\w+|asap|immediately|urgent)\b",
            text, re.IGNORECASE
        )
        if m:
            lead["timeline"] = m.group(0).strip()

    # Need / goal
    if _is_empty(lead, "need"):
        if any(w in lower for w in [
            "need", "looking for", "want to", "trying to", "goal", "problem",
            "challenge", "automate", "qualify", "scale", "inbound", "outbound",
        ]):
            lead["need"] = text.strip()[:200]

    return lead

def _next_missing_field(lead: Dict) -> Optional[Tuple[str, str]]:
    """Return (field_key, question) for the first still-empty qualification field."""
    for key, question in QUAL_FIELDS:
        if _is_empty(lead, key):
            return key, question
    return None

def _build_summary(lead: Dict) -> str:
    filled = [(k, lead.get(k, EMPTY)) for k, _ in QUAL_FIELDS if not _is_empty(lead, k)]
    if not filled:
        return ""
    return "; ".join(f"{k.title()}: {v}" for k, v in filled) + "."

def _qualification_status(lead: Dict) -> str:
    filled = sum(1 for k, _ in QUAL_FIELDS if not _is_empty(lead, k))
    total = len(QUAL_FIELDS)
    if filled == total:
        return "Fully Qualified"
    if filled >= 4:
        return "Qualified"
    return "In Progress"

# ── Offline fallback engine ───────────────────────────────────────────────────

def fallback_sales_engine(
    user_message: str,
    current_lead: Dict,
    faq_match: Optional[Dict],
) -> Tuple[str, Dict, str]:
    lower = user_message.lower().strip()
    lead = dict(current_lead) if current_lead else {}

    # Extract any inline fields from the message first
    lead = _extract_fields(user_message, lead)

    # 1. Booking intent — check for a slot name in the message
    for slot in MOCK_AVAILABLE_SLOTS:
        if slot.lower() in lower:
            database.book_appointment(
                lead.get("name", "Prospect"),
                slot,
                "Booked via Sales Agent",
                lead_email=lead.get("email", EMPTY),
            )
            lead["status"] = "Qualified & Booked"
            lead["summary"] = _build_summary(lead) + f" Demo booked: {slot}."
            return (
                f"Fantastic! I've locked in your demo for {slot}. "
                "A calendar invite will be sent shortly. Is there anything else before we meet?",
                lead,
                "offline_fallback",
            )

    if any(w in lower for w in ["book", "schedule", "appointment", "demo", "calendar", "meeting"]):
        slots_str = ", ".join(f'"{s}"' for s in MOCK_AVAILABLE_SLOTS)
        return (
            f"I'd be happy to arrange a live product demo! "
            f"Here are our open slots: {slots_str}. Which works for you?",
            lead,
            "offline_fallback",
        )

    # 2. FAQ answer — grounded only in the retrieved FAQ entry answer text
    if faq_match:
        faq_reply = faq_match["answer"]
        next_field = _next_missing_field(lead)
        if next_field:
            field_key, question = next_field
            if lead.get("name") and lead["name"] != EMPTY:
                transition = f"Hope that gives clear clarity, {lead['name']}. {question}"
            else:
                transition = f"To make sure this matches your specific requirements, {question.lower()}"
            return (
                f"{faq_reply}\n\n{transition}",
                lead,
                "offline_fallback",
            )
        return (
            f"{faq_reply}\n\nIs there anything else I can clarify for you, or would you like to lock in a live 15-minute demo?",
            lead,
            "offline_fallback",
        )

    # 3. Greeting
    if any(w in lower for w in ["hi", "hello", "hey", "good morning", "good afternoon", "howdy"]):
        return (
            "Hello! Welcome to FortiVex. I'm your autonomous sales consultant. I can answer any questions about our 24/7 AI voice pipeline, pricing, and integrations. May I start with your name?",
            lead,
            "offline_fallback",
        )

    # 4. Qualification state machine — ask the next missing field
    next_field = _next_missing_field(lead)
    if next_field:
        field_key, question = next_field
        if lead.get("name") and lead["name"] != EMPTY and field_key == "company":
            phrase = f"Pleasure to meet you, {lead['name']}! {question}"
        elif lead.get("company") and lead["company"] != EMPTY and field_key == "role":
            phrase = f"Great to connect with {lead['company']}! {question}"
        elif field_key == "need":
            phrase = f"Got it. {question}"
        elif field_key == "budget":
            phrase = f"Understood. {question}"
        elif field_key == "timeline":
            phrase = f"That makes total sense. {question}"
        else:
            phrase = f"Thanks for that! {question}"
        return (
            phrase,
            lead,
            "offline_fallback",
        )

    # 5. All fields filled — suggest booking
    lead["status"] = _qualification_status(lead)
    lead["summary"] = _build_summary(lead)
    return (
        f"Thank you, {lead.get('name', 'there')}! I have everything I need. "
        f"FortiVex sounds like a great fit for {lead.get('company', 'your team')}. "
        f"Can I book you a 15-minute demo? We have \"{MOCK_AVAILABLE_SLOTS[0]}\" or "
        f"\"{MOCK_AVAILABLE_SLOTS[1]}\" available.",
        lead,
        "offline_fallback",
    )

# ── Groq mode ─────────────────────────────────────────────────────────────────

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"]

def _get_recent_history(limit: int = 6) -> str:
    """Format recent conversation turns for context."""
    try:
        msgs = database.get_messages()
        if not msgs:
            return "No previous conversation turns."
        recent = msgs[-limit:]
        formatted = []
        for m in recent:
            role = "Prospect" if m["role"] == "user" else "Agent"
            formatted.append(f"{role}: {m['content']}")
        return "\n".join(formatted)
    except Exception:
        return "No previous conversation turns."

def _groq_reply(user_message: str, current_lead: Dict, faq_match: Optional[Dict], lang: str = "en-US") -> Dict:
    faq_section = ""
    if faq_match:
        faq_section = f"""AUTHORITATIVE FAQ MATCH:
Question: {faq_match['question']}
Answer: {faq_match['answer']}
Use the above verified facts as the primary ground truth for this topic."""
    else:
        faq_section = "No direct FAQ keyword match. Use your general FortiVex product knowledge and consultative sales expertise to provide an articulate, accurate, and helpful response."

    nf = _next_missing_field(current_lead)
    if nf:
        next_field_info = f'Next missing lead field to naturally discover: "{nf[0]}" (e.g., smoothly ask: "{nf[1]}"). Weave this in conversationally.'
    else:
        next_field_info = "All 7 lead qualification fields have been collected! Enthusiastically encourage booking a demo slot."

    lang_instruction = (
        "Respond in natural, conversational Hindi (Devanagari script)."
        if lang.startswith("hi")
        else "Respond in English."
    )

    history_text = _get_recent_history(limit=8)

    prompt = f"""You are an elite, consultative AI Sales Voice Agent for FortiVex.

FORTIVEX PRODUCT & COMPANY KNOWLEDGE:
- What FortiVex does: Autonomous AI Sales Voice Agent operating 24/7. Answers inbound prospect calls within 500ms, qualifies leads with BANT criteria, handles technical & commercial FAQs, and books demo appointments into team calendars with zero human delay.
- Pricing Tiers:
  * Starter: $49/month (up to 500 calls, core qualification, email support).
  * Professional: $149/month (unlimited inbound calls, live CRM sync, custom voice accents, live chat support).
  * Enterprise: Custom pricing with volume discounts, 1-hour critical SLA, custom webhook pipelines, dedicated account manager.
- Integrations: 1-click native integrations with HubSpot, Salesforce, Zoho CRM, Google Calendar, and Microsoft Outlook. Plus Zapier, Make, and webhook support.
- Security & Compliance: SOC 2 Type II certified, GDPR-compliant, TLS 1.3 in transit, AES-256 at rest, raw audio discarded after transcription, data isolation.
- Setup & Onboarding: Under 15 minutes, zero code required. Upload existing FAQs/docs, connect calendar, and go live.
- Free Trial: 14-day free trial on Professional tier with 100 free minutes, no credit card required.
- ROI & Impact: Eliminates 24-48 hr inbound response lag; converts 3x more demos; reduces customer acquisition costs by up to 65%; handles unlimited simultaneous calls.
- Voice & Languages: Sub-second voice synthesis in English, Hindi, Spanish, French, German.

RECENT CONVERSATION HISTORY (Review to avoid repeating questions or statements):
{history_text}

CURRENT LEAD CRM STATE (Already known fields - DO NOT re-ask what is already provided):
{json.dumps(current_lead, indent=2)}

{faq_section}

{next_field_info}

AVAILABLE DEMO SLOTS: {MOCK_AVAILABLE_SLOTS}

PROSPECT'S LATEST MESSAGE: "{user_message}"

BEHAVIOR GUIDELINES:
1. {lang_instruction}
2. Provide a knowledgeable, rich, consultative answer. Never give a blunt or evasive "I will get back to you" response. If the question asks about capabilities, technology, pricing, integrations, or use cases, explain clearly and convincingly.
3. Keep the spoken response natural, warm, and concise (2 to 3 sentences max) so it sounds fluid on voice text-to-speech.
4. Avoid repetitive formulas (do NOT always say "Thanks for sharing! By the way..."). Acknowledge what the prospect said and weave any follow-up question seamlessly.
5. If the prospect indicates interest in a demo, confirm or suggest one of the available slots.

Return ONLY a valid JSON object (no markdown formatting, no code blocks) with these exact keys:
- "reply": string — your spoken response to the prospect (2-3 sentences max)
- "name": string or null — prospect's name if mentioned in this turn or previous turns
- "company": string or null — company name
- "role": string or null — job title/role
- "email": string or null — email address
- "need": string or null — business challenge or automation goal
- "budget": string or null — budget or investment range
- "timeline": string or null — target start date or timeline
- "booked_slot": string or null — exact demo slot name if confirmed, otherwise null
- "summary": string — 1-sentence current lead status summary
"""

    headers = {
        "Authorization": f"Bearer {_get_groq_key()}",
        "Content-Type": "application/json",
    }

    last_error = None
    for model_name in GROQ_MODELS:
        try:
            resp = requests.post(
                GROQ_API_URL,
                headers=headers,
                json={
                    "model": model_name,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.4,
                    "response_format": {"type": "json_object"},
                },
                timeout=18,
            )
            if resp.status_code == 200:
                raw = resp.json()["choices"][0]["message"]["content"].strip()
                raw = re.sub(r"^```(?:json)?\s*", "", raw)
                raw = re.sub(r"\s*```$", "", raw)
                return json.loads(raw)
            else:
                last_error = f"Model {model_name} HTTP {resp.status_code}: {resp.text[:120]}"
        except Exception as e:
            last_error = f"Model {model_name} error: {e}"
            continue

    raise RuntimeError(f"All Groq models failed. Last error: {last_error}")

# ── Main entry point ──────────────────────────────────────────────────────────

def generate_sales_reply(user_message: str, lang: str = "en-US") -> Dict[str, Any]:
    """
    Returns:
      {
        "reply":       str,
        "mode":        "groq_ai" | "offline_fallback",
        "sentiment":   "positive" | "neutral" | "negative",
        "faq_matched": str | None,   # FAQ entry id, or None
        "lead":        dict
      }
    """
    current_lead = database.get_latest_lead() or {}
    sentiment = classify_sentiment(user_message)
    faq_match = find_faq(user_message)
    faq_id = faq_match["id"] if faq_match else None

    fallback_reason = None
    if check_groq_available():
        try:
            parsed = _groq_reply(user_message, current_lead, faq_match, lang=lang)

            updated_lead = {
                "name":     parsed.get("name")     or current_lead.get("name",     EMPTY),
                "company":  parsed.get("company")  or current_lead.get("company",  EMPTY),
                "role":     parsed.get("role")     or current_lead.get("role",     EMPTY),
                "email":    parsed.get("email")    or current_lead.get("email",    EMPTY),
                "need":     parsed.get("need")     or current_lead.get("need",     EMPTY),
                "budget":   parsed.get("budget")   or current_lead.get("budget",   EMPTY),
                "timeline": parsed.get("timeline") or current_lead.get("timeline", EMPTY),
                "sentiment": sentiment,
                "summary":  parsed.get("summary")  or current_lead.get("summary",  ""),
            }
            updated_lead["status"] = _qualification_status(updated_lead)

            booked = parsed.get("booked_slot")
            if booked:
                database.book_appointment(
                    updated_lead["name"],
                    booked,
                    "Booked via Groq AI Agent",
                    lead_email=updated_lead.get("email", EMPTY),
                )
                updated_lead["status"] = "Qualified & Booked"

            lead_record = database.upsert_lead(updated_lead)
            return {
                "reply": parsed.get("reply", "Thank you! How else can I help?"),
                "mode": "groq_ai",
                "sentiment": sentiment,
                "faq_matched": faq_id,
                "lead": lead_record,
            }
        except Exception as exc:
            fallback_reason = f"{type(exc).__name__}: {str(exc)[:180]}"
            print(f"[Agent] Groq error — using fallback: {exc}")

    # Offline fallback
    reply_text, updated_lead, mode = fallback_sales_engine(user_message, current_lead, faq_match)
    updated_lead["sentiment"] = sentiment
    if updated_lead.get("status") != "Qualified & Booked":
        updated_lead["status"] = _qualification_status(updated_lead)
    if not updated_lead.get("summary"):
        updated_lead["summary"] = _build_summary(updated_lead)
    lead_record = database.upsert_lead(updated_lead)

    return {
        "reply": reply_text,
        "mode": mode,
        "fallback_reason": fallback_reason,
        "sentiment": sentiment,
        "faq_matched": faq_id,
        "lead": lead_record,
    }


def generate_call_summary() -> Dict[str, Any]:
    """Generate a concise call summary from the saved SQLite lead, appointments, and transcript."""
    lead = database.get_latest_lead() or {}
    appointments = database.get_appointments()
    transcript = database.format_transcript()
    sentiment = lead.get("sentiment", "neutral")

    apt_text = f"Appointment booked for {appointments[0]['slot']}." if appointments else "No appointment booked yet."

    if check_groq_available() and transcript:
        for model_name in GROQ_MODELS:
            try:
                prompt = (
                    "Write a concise 2-sentence executive sales call summary based ONLY on this CRM state, "
                    "appointment status, and transcript. Be professional, crisp, and factual.\n\n"
                    f"Lead: {json.dumps(lead)}\n"
                    f"Appointment: {apt_text}\n"
                    f"Sentiment (basic estimate): {sentiment}\n"
                    f"Transcript:\n{transcript}"
                )
                resp = requests.post(
                    GROQ_API_URL,
                    headers={
                        "Authorization": f"Bearer {_get_groq_key()}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model_name,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.2,
                    },
                    timeout=15,
                )
                if resp.status_code == 200:
                    summary_text = resp.json()["choices"][0]["message"]["content"].strip()
                    break
            except Exception:
                continue
    else:
        base = _build_summary(lead) or "Initial prospect inquiry recorded."
        summary_text = f"{base} Sentiment: {sentiment} (basic estimate). {apt_text}"

    updated = database.upsert_lead({"summary": summary_text})
    return {"summary": summary_text, "lead": updated}
