import os
import sys

# Add the subfolder containing the real Flask app to the import path
BASE_DIR = os.path.dirname(__file__)
SUBDIR = os.path.join(BASE_DIR, 'version- 0.2')
if SUBDIR not in sys.path:
    sys.path.insert(0, SUBDIR)

# Import the Flask app instance from the subfolder's app.py
from app import app  # noqa: E402
