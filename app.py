from flask import Flask, request, jsonify
from twilio.rest import Client
import psycopg2, os, json
from psycopg2 import pool

app = Flask(__name__)

# Env vars (Render / Local)
DATABASE_URL = os.getenv("DATABASE_URL")
TWILIO_SID = os.getenv("TWILIO_SID")
TWILIO_AUTH = os.getenv("TWILIO_AUTH")
WHATSAPP_FROM = "whatsapp:+14155238886"  # Twilio sandbox number

twilio_client = Client(TWILIO_SID, TWILIO_AUTH)

# Setup Postgres connection pool
db_pool = pool.SimpleConnectionPool(
    1, 10, dsn=DATABASE_URL
)

def get_conn():
    return db_pool.getconn()

def put_conn(conn):
    db_pool.putconn(conn)

# Initialize schema
def init_db():
    conn = get_conn()
    conn.autocommit = True
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
    cur.close()
    put_conn(conn)

init_db()

@app.route("/webhook", methods=["POST"])
def whatsapp_webhook():
    data = request.form.to_dict()
    print("📩 Incoming data:", data)

    from_number = data.get("From")
    to_number = data.get("To")
    body = data.get("Body", "").strip()
    media_url = data.get("MediaUrl0") if int(data.get("NumMedia", 0)) > 0 else None

    conn = get_conn()
    conn.autocommit = True
    cur = conn.cursor()

    try:
        # Store raw message
        cur.execute("""
            INSERT INTO messages (from_number, to_number, body, media_url, raw_data)
            VALUES (%s, %s, %s, %s, %s)
        """, (from_number, to_number, body, media_url, json.dumps(data)))
        print("✅ Saved message to DB:", from_number, body, media_url)

        # Check if user exists
        cur.execute("SELECT * FROM users WHERE phone_number = %s;", (from_number,))
        user = cur.fetchone()

        if not user:
            # New user → insert record + send welcome
            cur.execute("""
                INSERT INTO users (phone_number, language, state)
                VALUES (%s, NULL, NULL)
                ON CONFLICT (phone_number) DO NOTHING
            """, (from_number,))

            twilio_client.messages.create(
                from_=WHATSAPP_FROM,
                to=from_number,
                body=(
                    "👋 Welcome! Please choose your preferred *Language* and *State*.\n\n"
                    "Reply in the format:\nLanguage: <Your Language>\nState: <Your State>"
                )
            )
        else:
            # Existing user → language/state update
            if "language:" in body.lower() and "state:" in body.lower():
                try:
                    parts = body.split("\n")
                    lang, state = None, None
                    for p in parts:
                        if "language" in p.lower():
                            lang = p.split(":")[1].strip()
                        if "state" in p.lower():
                            state = p.split(":")[1].strip()

                    if lang and state:
                        cur.execute("""
                            UPDATE users SET language=%s, state=%s WHERE phone_number=%s
                        """, (lang, state, from_number))

                        twilio_client.messages.create(
                            from_=WHATSAPP_FROM,
                            to=from_number,
                            body=f"✅ Got it! Saved Language = {lang}, State = {state}"
                        )
                except Exception as e:
                    print("⚠️ Parse error:", e)

    except Exception as e:
        print("❌ DB Insert error:", e)

    finally:
        cur.close()
        put_conn(conn)

    return "OK", 200

@app.route("/messages", methods=["GET"])
def get_messages():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, from_number, to_number, body, media_url, created_at, seen
        FROM messages
        WHERE seen = false
        ORDER BY created_at DESC LIMIT 20
    """)
    rows = cur.fetchall()
    cur.close()
    put_conn(conn)

    messages = [
        {
            "id": r[0],
            "from_number": r[1],
            "to_number": r[2],
            "body": r[3],
            "media_url": r[4],
            "created_at": r[5].isoformat(),
            "seen": r[6],
        }
        for r in rows
    ]
    return jsonify(messages)

@app.route("/messages/<int:message_id>/seen", methods=["POST"])
def mark_seen(message_id):
    conn = get_conn()
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("UPDATE messages SET seen = true WHERE id = %s;", (message_id,))
    cur.close()
    put_conn(conn)
    return jsonify({"status": "success", "message_id": message_id})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
