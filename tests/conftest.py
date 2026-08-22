import os

# Satisfy the Fernet 64-hex-char startup validation before any backend module
# that touches encryption.py is imported.
os.environ.setdefault("ENCRYPTION_SECRET", "0" * 64)
