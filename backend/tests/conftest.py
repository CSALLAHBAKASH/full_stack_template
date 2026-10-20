import os
import sys
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SESSION_SECRET"] = "test-session-secret-that-is-long-enough"
os.environ["BOOTSTRAP_ADMIN_EMAIL"] = "admin@example.com"
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "local-admin-password-change-me"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
