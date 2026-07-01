#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
python runtime/live_runtime.py
