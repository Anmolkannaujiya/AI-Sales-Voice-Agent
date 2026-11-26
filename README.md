# FortiVex — Autonomous AI Sales Voice Agent (MVP)

A simple, beginner-friendly Autonomous AI Sales Voice Agent built with **FastAPI**, **SQLite**, and a single **HTML/CSS/JavaScript** page.

---

## Features
- **Voice & Text Chat**: Speak in **English (`en-US`)** or **Hindi (`hi-IN`)** via the browser's Web Speech API (`SpeechRecognition` + `speechSynthesis`), or use the text box and **Send** button anytime as a fallback. No audio is uploaded or stored.
- **7-Field Lead Qualification**: Tracks `name`, `company`, `role`, `need`, `budget`, `timeline`, and `email` one question at a time.
- **Local FAQ Retrieval**: Matches product questions against `faq.json` using keyword matching. Uses Groq for phrasing only if `GROQ_API_KEY` is set; otherwise uses a rule-based fallback.
- **Basic Sentiment Estimate**: Tags user messages as `positive`, `neutral`, or `negative` using keyword rules (labeled as a basic estimate).
- **Mock Appointment & CRM**: Saves mock appointments (`lead_name`, `lead_email`, and chosen date/time), conversation transcript, and a short call summary to local SQLite (`sales_agent.db`).

---




1. **Show the Status Badges**: Point out the **Offline Fallback** (or **Groq AI**) badge in the top bar and the **English / Hindi** language selector.
2. **Test Voice or Text Input**:
   - Click the **🎤** button and say *"Hi, what does FortiVex cost?"* (or click the **Pricing** FAQ chip / type it).
   - Point out the spoken TTS reply, the **`📖 FAQ: pricing`** badge, and the **Sentiment (est.)** update.
3. **Walk Through Lead Qualification**:
   - Type or say: *"My name is Alex from Acme Corp, I'm a Sales Manager and my email is alex@acme.com."*
   - Show the **Lead Qualification (CRM)** panel updating `Name`, `Company`, `Role`, `Email`, and the progress bar, while the agent asks for the next missing field (`need`, `budget`, `timeline`).
   - Answer the remaining prompts (e.g., *"We want to automate inbound leads"*, *"Budget is $150/month"*, *"Timeline is next month"*).
4. **Book a Mock Appointment**:
   - In **Mock Appointment Booking**, verify `Lead name` and `Lead email` are pre-filled, pick a date/time (or click a quick slot like **Tomorrow 10:00 AM**), and click **Book Appointment**.
   - Show the **Appointment Status** and **Confirmed Appointments** card update.
5. **Generate Call Summary & Inspect CRM Record**:
   - Click **Generate Summary** to refresh the **Call Summary** box, and scroll through **Saved CRM Transcript (SQLite)** to show the full persisted mock CRM record.
6. **Reset for Next Demo**: Click **Reset Demo** in the header to clear SQLite and start fresh.
