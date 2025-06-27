#!/usr/bin/env python3
"""
image_food_logger.py – Flask webhook that:
1. Accepts an image via POST (Tasker share → HTTP Request action).
2. Sends the image to OpenAI Vision to get a nutrition estimate.
3. Uses Fitbit refresh_token flow to log the food item + calories/protein/etc.
"""

import os, json, base64, datetime, requests
import tempfile, urllib.request
from urllib.parse import urlparse
from pathlib import Path
from dotenv import load_dotenv
from flask import Flask, request, jsonify

load_dotenv("/root/calorie-bot/.env")

# --- Config -----------------------------------------------------------------
OPENAI_API_KEY     = os.environ["OPENAI_API_KEY"]
FITBIT_CLIENT_ID   = os.environ["FITBIT_CLIENT_ID"]
FITBIT_SECRET      = os.environ["FITBIT_SECRET"]
FITBIT_REFRESH     = os.environ["REFRESH_TOKEN"]
FITBIT_AUTH_HEADER = os.environ["AUTH_HEADER"]  # "Basic <base64(id:secret)>"
SAVE_DIR           = Path(os.environ.get("SAVE_DIR", "/root/calorie-bot/images"))
WEBHOOK_KEY        = os.environ.get("WEBHOOK_KEY")     # simple header auth
PORT               = int(os.environ.get("PORT", "5000"))

HEADERS_OPENAI = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
HEADERS_FITBIT = {
    "Authorization": FITBIT_AUTH_HEADER,
    "Content-Type": "application/x-www-form-urlencoded",
}

# --- Flask app --------------------------------------------------------------
app = Flask(__name__)
SAVE_DIR.mkdir(parents=True, exist_ok=True)


def refresh_fitbit_tokens(refresh_token: str) -> dict:
    """Get new access/refresh tokens from Fitbit."""
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    r = requests.post("https://api.fitbit.com/oauth2/token", headers=HEADERS_FITBIT, data=data)
    r.raise_for_status()
    update_tokens_in_env(r.json())
    return r.json()

def update_tokens_in_env(tokens: str) -> dict:
    new_refresh = tokens["refresh_token"]
    env_path = Path("/root/calorie-bot/.env")
    text = env_path.read_text().splitlines()
    text = [line for line in text if not line.startswith("REFRESH_TOKEN=")]
    text.append(f"REFRESH_TOKEN={new_refresh}")
    env_path.write_text("\n".join(text) + "\n")

def log_food_to_fitbit(access_token: str, food: str, cal: int, protein: int = None):
    """Create a custom food entry (manual log) – simplest method."""
    # Simplest: log a manual entry with foodName + cal. Fitbit needs at least
    # calories, amount, unitId, mealTypeId, and foodName OR foodId.
    today = datetime.date.today().strftime("%Y-%m-%d")
    now   = datetime.datetime.now().strftime("%H:%M:%S")
    body = {
        "foodName": food,
        "mealTypeId": 6,          # 6 = Anytime
        "unitId": 147,            # Serving
        "amount": 1,
        "calories": cal,
        "date": today,
        "time": now,
    }
    headers = {"Authorization": f"Bearer {access_token}"}
    r = requests.post("https://api.fitbit.com/1/user/-/foods/log.json", headers=headers, data=body)
    r.raise_for_status()
    return r.json()

def log_specific_food_to_fitbit(access_token: str, food_id: str, unit_id: int, serving_amount: int):
    today = datetime.date.today().strftime("%Y-%m-%d")
    now   = datetime.datetime.now().strftime("%H:%M:%S")
    body = {
        "foodId": food_id,
        "mealTypeId": 6,          # 6 = Anytime
        "unitId": unit_id,            # Serving
        "amount": serving_amount,
        "date": today,
        "time": now,
    }
    headers = {"Authorization": f"Bearer {access_token}"}
    r = requests.post("https://api.fitbit.com/1/user/-/foods/log.json", headers=headers, data=body)
    r.raise_for_status()
    return r.json()

def search_food(access_token: str, food_search: str):
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"query": food_search}

    r = requests.get('https://api.fitbit.com/1/foods/search.json', params=params, headers=headers)
    r.raise_for_status()
    return r.json()

def analyze_image(img_url: str) -> dict:
    """
    Call OpenAI Vision with a public image URL and get nutrition JSON back.
    """
    system_msg = {
        "role": "system",
        "content": (
            "You are a nutrition assistant. Reply with **ONLY** valid JSON: "
            '{"food":"<name>","calories":123,"protein":10}. '
            "If unsure, guess."
        ),
    }
    user_msg = {
        "role": "user",
        "content": [
            {  # image part
                "type": "image_url",
                "image_url": {"url": img_url}
            },
            {  # text part (required)
                "type": "text",
                "text": "Identify the food, estimate calories and protein. Respond only in JSON."
            }
        ],
    }

    payload = {
        "model": "o3",          # model with vision support
        "messages": [system_msg, user_msg],
        "max_completion_tokens": 500,
    }
    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
        json=payload,
        timeout=60,
    )
    if r.status_code != 200:
        raise RuntimeError(f"OpenAI vision error {r.status_code}: {r.text}")
    return json.loads(r.json()["choices"][0]["message"]["content"].strip())

def analyze_food(food: str) -> dict:
    """
    Call OpenAI Vision with a public image URL and get nutrition JSON back.
    """
    system_msg = {
        "role": "system",
        "content": (
            "You are a nutrition assistant. Reply with **ONLY** valid JSON: "
            '{"food":"<name>","calories":123,"protein":10}. '
            "If unsure, guess."
        ),
    }
    user_msg = {
        "role": "user",
        "content": [
            {  # text part (required)
                "type": "text",
                "text": f"Estimate calories and protein for '{food}'. Respond only in JSON."
            }
        ],
    }

    payload = {
        "model": "o3",          # model with vision support
        "messages": [system_msg, user_msg],
        "max_completion_tokens": 500,
    }
    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
        json=payload,
        timeout=60,
    )
    if r.status_code != 200:
        raise RuntimeError(f"OpenAI error {r.status_code}: {r.text}")
    return json.loads(r.json()["choices"][0]["message"]["content"].strip())

@app.route("/ping", methods=["POST"])
def ping(): return "pong"

@app.route("/image_webhook", methods=["POST"])
def handle_webhook():
    # --- Optional header-based auth ----------------------------------------
    if WEBHOOK_KEY:
        key = request.headers.get("X-Webhook-Key")
        if key != WEBHOOK_KEY:
            return jsonify({"error": "unauthorized"}), 401

    if "image" not in request.files:
        return jsonify({"error": "no image field"}), 400

    img_file = request.files["image"]
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    save_path = SAVE_DIR / f"{timestamp}_{img_file.filename}"
    img_file.save(save_path)

    # 1. Vision analysis
    try:
        nutrition = analyze_image(save_path)
    except Exception as e:
        return jsonify({"error": "vision_failed", "detail": str(e)}), 500

    try:
        tokens = refresh_fitbit_tokens(FITBIT_REFRESH)
    except Exception as e:
        return jsonify({"error": "fitbit_refresh_failed", "detail": str(e)}), 500
    
    try:
        log_resp = log_food_to_fitbit(
            tokens["access_token"],
            nutrition["food"],
            nutrition["calories"],
            nutrition.get("protein"),
        )
    except Exception as e:
        return jsonify({"error": "fitbit_log_failed", "detail": str(e)}), 500
    
    return jsonify({"status": "ok", "vision": nutrition, "fitbit": log_resp})

@app.route("/food_webook", methods=["POST"])
def handle_webhook():
    if WEBHOOK_KEY:
        key = request.headers.get("X-Webhook-Key")
        if key != WEBHOOK_KEY:
            return jsonify({"error": "unauthorized"}), 401

    food = request.json.get("food")
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    # 1. Vision analysis
    try:
        nutrition = analyze_food(food)
    except Exception as e:
        return jsonify({"error": "vision_failed", "detail": str(e)}), 500

    try:
        tokens = refresh_fitbit_tokens(FITBIT_REFRESH)
    except Exception as e:
        return jsonify({"error": "fitbit_refresh_failed", "detail": str(e)}), 500
    
    try:
        log_resp = log_food_to_fitbit(
            tokens["access_token"],
            nutrition["food"],
            nutrition["calories"],
            nutrition.get("protein"),
        )
    except Exception as e:
        return jsonify({"error": "fitbit_log_failed", "detail": str(e)}), 500
    
    return jsonify({"status": "ok", "vision": nutrition, "fitbit": log_resp})

@app.route("/url_webhook", methods=["POST"])
def handle_url_webhook():
    # Basic header auth
    if WEBHOOK_KEY and request.json.get("secret") != WEBHOOK_KEY:
        return jsonify({"error": "unauthorized"}), 401

    img_url = request.json.get("image_url")

    if not img_url:
        return jsonify({"error": "no image_url"}), 400

    try:
        nutrition = analyze_image(img_url)
    except Exception as e:
        return jsonify({"error": "vision_failed", "detail": str(e)}), 500

    try:
        tokens = refresh_fitbit_tokens(FITBIT_REFRESH)
    except Exception as e:
        return jsonify({"error": "fitbit_refresh_failed", "detail": str(e)}), 500
    

    # Log food
    try:
        log_resp = log_food_to_fitbit(
            tokens["access_token"],
            nutrition["food"],
            nutrition["calories"],
            nutrition.get("protein"),
        )
    except Exception as e:
        return jsonify({"error": "fitbit_log_failed", "detail": str(e)}), 500

    return jsonify({"status": "ok", "vision": nutrition, "fitbit": log_resp})

@app.route("/specific_food", methods=["POST"])
def handle_specific_food_webhook():
    # Basic header auth
    if WEBHOOK_KEY and request.json.get("secret") != WEBHOOK_KEY:
        return jsonify({"error": "unauthorized"}), 401

    food_id = request.json.get("food_id")
    unit_id = request.json.get("unit_id")
    serving_amount = request.json.get("serving_amount")

    if not food_id:
        return jsonify({"error": "no food_id"}), 400

    try:
        tokens = refresh_fitbit_tokens(FITBIT_REFRESH)
    except Exception as e:
        return jsonify({"error": "fitbit_refresh_failed", "detail": str(e)}), 500
    

    # Log food
    log_resp = log_specific_food_to_fitbit(
        tokens["access_token"], food_id, unit_id, serving_amount
    )
    return jsonify({"status": "ok", "fitbit": log_resp})

@app.route("/search_food", methods=["GET"])
def handle_search_food_webhook():
    # Basic header auth
    if WEBHOOK_KEY and request.json.get("secret") != WEBHOOK_KEY:
        return jsonify({"error": "unauthorized"}), 401

    food_to_search = request.json.get("search_term")

    if not food_to_search:
        return jsonify({"error": "no search team"}), 400

    # Refresh Fitbit tokens
    try:
        tokens = refresh_fitbit_tokens(FITBIT_REFRESH)
    except Exception as e:
        return jsonify({"error": "fitbit_refresh_failed", "detail": str(e)}), 500
    

    # search food
    log_resp = search_food(
        tokens["access_token"], food_to_search
    )
    return jsonify({"status": "ok", "fitbit": log_resp})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
