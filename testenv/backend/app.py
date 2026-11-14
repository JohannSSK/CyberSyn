from flask import Flask, jsonify, render_template, request

app = Flask(__name__)


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    data = request.get_json()
    # TODO: Backend implements this
    return jsonify({})


@app.route("/api/admin", methods=["POST"])
def admin_add_remove():
    data = request.get_json()
    # TODO: Backend implements this
    return jsonify({})


@app.route("/api/admin/employee", methods=["POST"])
def employee_add_remove():
    data = request.get_json()
    # TODO: Backend implements this
    return jsonify({})


@app.route("/api/admin/employee/login", methods=["POST"])
def employee_login():
    data = request.get_json()
    # TODO: Backend implements this
    return jsonify({})


@app.route("/api/admin/employee/settings", methods=["POST"])
def settings_update():
    data = request.get_json()
    # TODO: Backend implements this
    return jsonify({})


@app.route("/api/admin/employee/chat", methods=["POST"])
def chat():
    data = request.get_json()
    # TODO: Backend implements this
    return jsonify({})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
