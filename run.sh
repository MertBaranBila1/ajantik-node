#!/usr/bin/env bash
cd "$(dirname "$0")"
exec ./venv/bin/python -m ajantik config.json
