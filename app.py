from flask import Flask, request, jsonify
import psycopg2, os, json

app = Flask(__name__)

# Read Render Postgres URL from env
DATABASE_URL = os.getenv("DATABASE_URL")

# Ensure table exists
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
    body = data.get("Body", "")
    media_url = data.get("MediaUrl0") if int(data.get("NumMedia", 0)) > 0 else None

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO messages (from_number, to_number, body, media_url, raw_data)
        VALUES (%s, %s, %s, %s, %s)
    """, (from_number, to_number, body, media_url, json.dumps(data)))
    conn.commit()
    cur.close()
    conn.close()

    return "OK", 200

@app.route("/messages", methods=["GET"])
def get_messages():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, from_number, to_number, body, media_url, created_at, seen
        FROM messages
        WHERE seen = false
        ORDER BY created_at DESC LIMIT 20
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
