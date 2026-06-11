#!/bin/bash
# Start script for Render - runs both FastAPI and Telegram Bot

# Start FastAPI in background
uvicorn bot:fastapi_app --host 0.0.0.0 --port 8000 &

# Wait a moment for FastAPI to start
sleep 3

# Start Telegram Bot (main process)
python bot.py
