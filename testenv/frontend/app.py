import json
import random
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

with open("mock_responses.json", "r", encoding="utf-8") as f:
    MOCK_DATA = json.load(f)


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/<path:subpath>", methods=["GET", "POST"])
def mock_api(subpath):
    route = f"/api/{subpath}"
    if route in MOCK_DATA:
        return jsonify(random.choice(MOCK_DATA[route]))
    return jsonify({"error": True, "error_message": f"Unknown route: {route}"}), 404


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
