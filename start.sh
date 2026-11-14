#!/bin/sh
cd "$(dirname "$0")" && exec python3 audio_processor.py serve "$@"
