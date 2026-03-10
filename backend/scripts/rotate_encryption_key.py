import os
import sys
import base64
import asyncio
from cryptography.fernet import Fernet
from sqlalchemy import select
from backend.database import SessionLocal
from backend.models import OrgLLMConfig, RedditAccount, AuditLog

def get_fernet(secret_hex: str) -> Fernet:
    if len(secret_hex) != 64:
        raise ValueError("Secret must be exactly 64 hex characters (32 bytes).")
    key_bytes = bytes.fromhex(secret_hex)
    return Fernet(base64.urlsafe_b64encode(key_bytes))

async def main():
    old_secret = os.environ.get("OLD_ENCRYPTION_SECRET")
    new_secret = os.environ.get("NEW_ENCRYPTION_SECRET")
    
    if not old_secret or not new_secret:
        print("Please set OLD_ENCRYPTION_SECRET and NEW_ENCRYPTION_SECRET environment variables.", file=sys.stderr)
        sys.exit(1)
        
    old_fernet = get_fernet(old_secret)
    new_fernet = get_fernet(new_secret)
    
    async with SessionLocal() as db:
        # 1. Rotate OrgLLMConfig
        result = await db.execute(select(OrgLLMConfig).where(OrgLLMConfig.encrypted_api_key.is_not(None)))
        configs = result.scalars().all()
        for config in configs:
            try:
                decrypted = old_fernet.decrypt(config.encrypted_api_key.encode()).decode()
                config.encrypted_api_key = new_fernet.encrypt(decrypted.encode()).decode()
                config.encrypted_with_key_version += 1
                
                db.add(AuditLog(
                    org_id=config.org_id,
                    action="ENCRYPTION_KEY_ROTATED",
                    details={"model": "OrgLLMConfig", "id": config.id, "new_version": config.encrypted_with_key_version}
                ))
            except Exception as e:
                print(f"Failed to rotate OrgLLMConfig {config.id}: {e}", file=sys.stderr)
                
        # 2. Rotate RedditAccount
        result = await db.execute(select(RedditAccount).where(RedditAccount.encrypted_secret.is_not(None)))
        accounts = result.scalars().all()
        for account in accounts:
            try:
                decrypted = old_fernet.decrypt(account.encrypted_secret.encode()).decode()
                account.encrypted_secret = new_fernet.encrypt(decrypted.encode()).decode()
                account.encrypted_with_key_version += 1
                
                db.add(AuditLog(
                    org_id=account.org_id,
                    action="ENCRYPTION_KEY_ROTATED",
                    details={"model": "RedditAccount", "id": account.id, "new_version": account.encrypted_with_key_version}
                ))
            except Exception as e:
                print(f"Failed to rotate RedditAccount {account.id}: {e}", file=sys.stderr)
                
        # Commit all key updates and audit logs in a single transaction
        await db.commit()
        print("Successfully rotated encryption keys for OrgLLMConfig and RedditAccount.")

if __name__ == "__main__":
    asyncio.run(main())
