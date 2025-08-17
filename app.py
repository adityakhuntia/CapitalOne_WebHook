from flask import Flask, request

app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
def whatsapp_webhook():
    """
    Endpoint to receive incoming WhatsApp messages and button clicks from Twilio.
    Twilio sends x-www-form-urlencoded data.
    """
    data = request.form.to_dict()
    print("Incoming data:", data)

    # Check if it's a button click
    if "ButtonId" in data:
        print(f"User clicked: {data.get('ButtonText')} (ID: {data.get('ButtonId')})")
    else:
        print(f"User message: {data.get('Body')}")

    # Respond back to Twilio (optional)
    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
