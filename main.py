import os
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional

import database
import agent

app = FastAPI(title="FortiVex Autonomous AI Sales Voice Agent", version="1.0.0")

# Request Models
class ChatRequest(BaseModel):
    message: str
    lang: Optional[str] = "en-US"

class BookingRequest(BaseModel):
    slot: str
    name: Optional[str] = None
    email: Optional[str] = None
    notes: Optional[str] = "Booked via Dashboard"

@app.on_event("startup")
def on_startup():
    # Initialize SQLite tables on server startup
    database.init_db()

# Health check route
@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "groq_active": agent.check_groq_available(),
        "database": "sqlite3",
        "service": "FortiVex Sales Voice Agent"
    }

# Main Chat route
@app.post("/api/chat")
def chat_endpoint(payload: ChatRequest):
    user_text = payload.message.strip()
    if not user_text:
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    
    # Save user message first so transcript includes it
    user_sentiment = agent.classify_sentiment(user_text)
    database.save_message(role="user", content=user_text, sentiment=user_sentiment)

    # Generate response
    result = agent.generate_sales_reply(user_text, lang=payload.lang or "en-US")
    reply_text = result["reply"]
    mode = result["mode"]
    sentiment = result.get("sentiment", user_sentiment)

    # Save assistant message and sync full transcript to CRM record
    database.save_message(role="assistant", content=reply_text, sentiment="neutral")
    lead = database.upsert_lead({})
    
    # Get updated appointments
    appointments = database.get_appointments()
    
    return {
        "reply": reply_text,
        "mode": mode,
        "fallback_reason": result.get("fallback_reason"),
        "sentiment": result.get("sentiment", "neutral"),
        "faq_matched": result.get("faq_matched"),
        "lead": lead,
        "appointments": appointments,
        "available_slots": agent.MOCK_AVAILABLE_SLOTS
    }

# Mock appointment booking route
@app.post("/api/book")
def book_endpoint(payload: BookingRequest):
    slot = payload.slot.strip()
    if not slot:
        raise HTTPException(status_code=400, detail="Appointment date/time is required")

    latest_lead = database.get_latest_lead() or {}
    lead_name = (payload.name or "").strip() or latest_lead.get("name", "Not provided")
    lead_email = (payload.email or "").strip() or latest_lead.get("email", "Not provided")

    apt = database.book_appointment(
        lead_name,
        slot,
        payload.notes or "Mock Appointment",
        lead_email=lead_email,
    )

    # Update mock CRM record with latest name, email, booking status, and summary
    lead_updates = {
        "status": "Qualified & Booked",
        "summary": f"{lead_name if lead_name != 'Not provided' else 'Prospect'} ({lead_email}) booked a mock appointment for {slot}.",
    }
    if lead_name != "Not provided":
        lead_updates["name"] = lead_name
    if lead_email != "Not provided":
        lead_updates["email"] = lead_email

    updated_lead = database.upsert_lead(lead_updates)

    return {
        "message": f"Mock appointment booked for {slot}",
        "appointment": apt,
        "appointments": database.get_appointments(),
        "lead": updated_lead,
    }


# Generate short call summary & refresh mock CRM record
@app.post("/api/summary")
def summary_endpoint():
    return agent.generate_call_summary()

# CRM & Analytics endpoint
@app.get("/api/crm")
def get_crm_data():
    return {
        "groq_active": agent.check_groq_available(),
        "lead": database.get_latest_lead() or {
            "name": "Not provided",
            "company": "Not provided",
            "role": "Not provided",
            "email": "Not provided",
            "need": "Not provided",
            "budget": "Not provided",
            "timeline": "Not provided",
            "sentiment": "neutral",
            "status": "In Progress",
            "summary": "No active conversation yet.",
            "transcript": ""
        },
        "appointments": database.get_appointments(),
        "messages": database.get_messages(),
        "available_slots": agent.MOCK_AVAILABLE_SLOTS
    }

# Reset demo route
@app.post("/api/reset")
def reset_endpoint():
    database.reset_database()
    return {"status": "ok", "message": "Demo data reset successfully"}

# Mount static folder
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Home route serving the single HTML/CSS/JS page
@app.get("/")
def serve_home():
    return FileResponse("static/index.html")
