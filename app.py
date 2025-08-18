from flask import Flask, request, jsonify
from twilio.rest import Client
import psycopg2, os, json

app = Flask(__name__)

# Read Render Postgres URL + Twilio creds from env
DATABASE_URL = os.getenv("DATABASE_URL")
TWILIO_SID = os.getenv("TWILIO_SID")
TWILIO_AUTH = os.getenv("TWILIO_AUTH")
WHATSAPP_FROM = "whatsapp:+14155238886"  # Twilio sandbox number

twilio_client = Client(TWILIO_SID, TWILIO_AUTH)

# Ensure tables exist
def init_db():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            from_number TEXT,
            to_number TEXT,
            body TEXT,
            media_url TEXT,
            raw_data JSONB,
            created_at TIMESTAMP DEFAULT NOW(),
            seen BOOL DEFAULT FALSE
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            phone_number TEXT PRIMARY KEY,
            language TEXT,
            state TEXT,
            joined_at TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

init_db()
@app.route("/webhook", methods=["POST"])
def whatsapp_webhook():
    data = request.form.to_dict()
    print("Incoming data:", data)

    from_number = data.get("From")
    to_number = data.get("To")
    body = data.get("Body", "").strip()
    media_url = data.get("MediaUrl0") if int(data.get("NumMedia", 0)) > 0 else None

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # Always store the raw message
    cur.execute("""
        INSERT INTO messages (from_number, to_number, body, media_url, raw_data)
        VALUES (%s, %s, %s, %s, %s)
    """, (from_number, to_number, body, media_url, json.dumps(data)))

    # Get user if exists
    cur.execute("SELECT phone_number, language, state FROM users WHERE phone_number = %s;", (from_number,))
    user = cur.fetchone()

    # 1️⃣ Brand new user → insert & send welcome
    if not user:
        cur.execute(
            "INSERT INTO users (phone_number, language, state) VALUES (%s, %s, %s) "
            "ON CONFLICT (phone_number) DO NOTHING",
            (from_number, None, None)
        )
        conn.commit()

        twilio_client.messages.create(
            from_=WHATSAPP_FROM,
            to=from_number,
            body=(
                "👋 Welcome! Please choose your preferred *Language* and *State*.\n\n"
                "Reply in the format:\nLanguage: <Your Language>\nState: <Your State>"
            )
        )

    else:
        lang, state = user[1], user[2]

        # 2️⃣ User exists but hasn’t set language/state yet
        if (not lang or not state) and ("language:" in body.lower() and "state:" in body.lower()):
            try:
                parts = body.split("\n")
                new_lang, new_state = None, None
                for p in parts:
                    if "language" in p.lower():
                        new_lang = p.split(":", 1)[1].strip()
                    if "state" in p.lower():
                        new_state = p.split(":", 1)[1].strip()

                if new_lang and new_state:
                    cur.execute(
                        "UPDATE users SET language=%s, state=%s WHERE phone_number=%s",
                        (new_lang, new_state, from_number)
                    )
                    conn.commit()

                    twilio_client.messages.create(
                        from_=WHATSAPP_FROM,
                        to=from_number,
                        body=f"✅ Got it! Saved Language = {new_lang}, State = {new_state}"
                    )
            except Exception as e:
                print("Parse error:", e)

        # 3️⃣ User already has language & state → treat as normal query
        elif lang and state:
            # you can plug in your assistant logic here
            #twilio_client.messages.create(
            #    from_=WHATSAPP_FROM,
            #    to=from_number,
            #    body=f"Hi! You’re registered with Language = {lang}, State = {state}. How can I help today?"
            #)
            continue

    conn.commit()
    cur.close()
    conn.close()

    return "OK", 200



@app.route("/messages", methods=["GET"])
def get_messages():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("""
        SELECT m.id, m.from_number, m.to_number, m.body, m.media_url, m.created_at, m.seen,
               u.language, u.state
        FROM messages m
        LEFT JOIN users u ON m.from_number = u.phone_number
        WHERE m.seen = false
        ORDER BY m.created_at DESC
        LIMIT 20
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    messages = [
        {
            "id": r[0],
            "from_number": r[1],
            "to_number": r[2],
            "body": r[3],
            "media_url": r[4],
            "created_at": r[5].isoformat(),
            "seen": r[6],
            "language": r[7],
            "state": r[8],
        }
        for r in rows
    ]
    return jsonify(messages)


@app.route("/messages/<int:message_id>/seen", methods=["POST"])
def mark_seen(message_id):
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("UPDATE messages SET seen = true WHERE id = %s;", (message_id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"status": "success", "message_id": message_id})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
