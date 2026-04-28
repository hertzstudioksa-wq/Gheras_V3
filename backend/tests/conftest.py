"""Shared pytest fixtures and env bootstrap for backend tests."""
import os
import sys
from dotenv import load_dotenv

# Load backend .env so MONGO_URL / DB_NAME etc are available before db.py imports.
load_dotenv("/app/backend/.env")
# Also load frontend .env so REACT_APP_BACKEND_URL is available for HTTP tests.
load_dotenv("/app/frontend/.env")

# Make sure /app/backend is on sys.path so `from services.X import Y` works.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
