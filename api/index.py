import os
import sys

# Vercel invokes this file from within the /api directory; the app package sits
# one level up and must be importable before FastAPI is constructed.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app  # noqa: E402

__all__ = ["app"]
