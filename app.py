import os
import sys
from importlib.util import spec_from_file_location, module_from_spec

# Add the subfolder containing the real Flask app to the import path
BASE_DIR = os.path.dirname(__file__)
SUBDIR = os.path.join(BASE_DIR, 'version- 0.2')
if SUBDIR not in sys.path:
    sys.path.insert(0, SUBDIR)

# Load the subfolder's app.py as a uniquely named module to avoid circular import with this file
_sub_app_path = os.path.join(SUBDIR, 'app.py')
_spec = spec_from_file_location('app_submodule', _sub_app_path)
_mod = module_from_spec(_spec)
sys.modules['app_submodule'] = _mod
assert _spec and _spec.loader
_spec.loader.exec_module(_mod)  # type: ignore[attr-defined]

# Expose the Flask app for Gunicorn as 'app'
app = getattr(_mod, 'app')
