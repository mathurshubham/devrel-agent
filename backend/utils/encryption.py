import os
import base64
from cryptography.fernet import Fernet

def _validate_and_get_fernet() -> Fernet:
    secret_hex = os.environ.get('ENCRYPTION_SECRET', '')
    if len(secret_hex) != 64:
        raise ValueError(
            f'ENCRYPTION_SECRET must be exactly 64 hex characters (32 bytes). '
            f'Got {len(secret_hex)} characters. '
            f'Generate with: python -c "import secrets; print(secrets.token_hex(32))"'
        )
    key_bytes = bytes.fromhex(secret_hex)
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(fernet_key)

# Instantiated once at module import — validates on startup.
_fernet = _validate_and_get_fernet()

def encrypt(plaintext: str) -> str:
    return _fernet.encrypt(plaintext.encode()).decode()

def decrypt(token: str) -> str:
    return _fernet.decrypt(token.encode()).decode()
