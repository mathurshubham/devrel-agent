import os
import base64
from cryptography.fernet import Fernet

# In-memory cache for Fernet instances to avoid redundant key derivation
_fernet_cache = {}

def _get_fernet_for_version(version: int = 1) -> Fernet:
    """Fetch or derive the Fernet instance for a specific key version."""
    if version in _fernet_cache:
        return _fernet_cache[version]
    
    # Try VERSION_SPECIFIC variable, fall back to default ENCRYPTION_SECRET for V1
    env_key = f'ENCRYPTION_SECRET_V{version}'
    secret_hex = os.environ.get(env_key)
    
    if not secret_hex and version == 1:
        secret_hex = os.environ.get('ENCRYPTION_SECRET', '')
        
    if not secret_hex:
        raise ValueError(f"No encryption secret found for version {version} (Checked {env_key})")

    if len(secret_hex) != 64:
        raise ValueError(
            f'ENCRYPTION_SECRET_V{version} must be exactly 64 hex characters (32 bytes). '
            f'Got {len(secret_hex)} characters. '
        )
        
    key_bytes = bytes.fromhex(secret_hex)
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    _fernet_cache[version] = Fernet(fernet_key)
    return _fernet_cache[version]

def validate_primary_key():
    """Trigger validation of the primary (v1) key on startup."""
    _get_fernet_for_version(1)

def encrypt(plaintext: str, version: int = 1) -> str:
    """Encrypt using a specific key version."""
    f = _get_fernet_for_version(version)
    return f.encrypt(plaintext.encode()).decode()

def decrypt(token: str, version: int = 1) -> str:
    """Decrypt using a specific key version."""
    f = _get_fernet_for_version(version)
    return f.decrypt(token.encode()).decode()
