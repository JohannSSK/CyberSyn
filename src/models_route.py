import json
import urllib.request

from flask import jsonify, request

SKIP = ("tts", "image", "embedding", "lyria", "veo", "imagen", "aqa", "robotics", "live", "audio", "computer-use", "transcribe", "realtime", "search", "instruct", "moderation", "dall", "whisper", "davinci", "babbage")


def fetch_json(url, headers):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def gemini_models(key):
    body = fetch_json("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200", {"x-goog-api-key": key})
    names = []
    for m in body.get("models", []):
        name = m.get("name", "").replace("models/", "")
        if "generateContent" not in m.get("supportedGenerationMethods", []):
            continue
        if not name.startswith("gemini") or any(s in name for s in SKIP):
            continue
        names.append(name)
    return ["gemini/" + n for n in sorted(names)]


def openai_models(key):
    body = fetch_json("https://api.openai.com/v1/models", {"Authorization": "Bearer " + key})
    ids = [m["id"] for m in body.get("data", [])]
    return sorted(i for i in ids if i.startswith(("gpt-", "o1", "o3", "o4")) and not any(s in i for s in SKIP))


def anthropic_models(key):
    body = fetch_json("https://api.anthropic.com/v1/models", {"x-api-key": key, "anthropic-version": "2023-06-01"})
    return [m["id"] for m in body.get("data", [])]


def register(app):
    @app.post("/api/admin/employee/models")
    def list_models():
        data = request.get_json(silent=True) or {}
        key = str(data.get("API_KEY") or "").strip()
        if not key:
            return jsonify({"models": [], "message": "Paste an API key first."}), 400
        try:
            if key.startswith("AIza"):
                models = gemini_models(key)
            elif key.startswith("sk-ant-"):
                models = anthropic_models(key)
            elif key.startswith("sk-"):
                models = openai_models(key)
            else:
                models = gemini_models(key)
        except Exception as exc:
            return jsonify({"models": [], "message": "Could not load models: " + str(exc)}), 502
        return jsonify({"models": models})

