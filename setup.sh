#!/usr/bin/env bash
set -e

echo "==> 1. Creating Python virtual environment (.venv)..."
python3 -m venv .venv

echo "==> 2. Upgrading pip..."
./.venv/bin/pip install --upgrade pip

echo "==> 3. Installing dependencies from requirements.txt..."
./.venv/bin/pip install -r requirements.txt

echo "==> 4. Pre-downloading Zero-Shot ML model..."
./.venv/bin/python -c "from transformers import pipeline; pipeline('zero-shot-classification', model='valhalla/distilbart-mnli-12-1')"

echo ""
echo "==> Setup complete."

# Detect actual running shell (checks STARSHIP_SHELL and parent process)
PARENT_SHELL=$(ps -p $PPID -o comm= 2>/dev/null || basename "$SHELL")

if [ "$STARSHIP_SHELL" = "fish" ] || [ "$PARENT_SHELL" = "fish" ]; then
    echo "Fish shell detected. Activating .venv in fish..."
    exec fish -C "source .venv/bin/activate.fish"
else
    echo "Bash/Zsh detected. Activating .venv..."
    exec "$SHELL" --rcfile <(echo "source ~/.bashrc 2>/dev/null; source .venv/bin/activate")
fi
