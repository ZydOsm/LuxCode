#!/usr/bin/env bash
# Build standalone leetcode-eval binaries with PyInstaller (CLI + desktop GUI).
set -euo pipefail

pip install -r requirements.txt

pyinstaller --onefile --name leetcode-eval \
  --hidden-import=openai \
  --hidden-import=anthropic \
  --hidden-import=google.genai \
  cli.py

pyinstaller --onefile --windowed --name leetcode-eval-gui \
  --hidden-import=openai \
  --hidden-import=anthropic \
  --hidden-import=google.genai \
  --hidden-import=customtkinter \
  --collect-data=customtkinter \
  gui.py

echo "CLI binary built at dist/leetcode-eval"
echo "GUI binary built at dist/leetcode-eval-gui"
