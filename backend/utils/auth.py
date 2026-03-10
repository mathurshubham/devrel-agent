import os
import httpx
import jwt
from jwt import PyJWKClient
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Clerk configuration
CLERK_FRONTEND_API = os.getenv("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY", "")
# Extract the domain from the publishable key if it's in the format pk_test_...
# Realistically, the user should provide CLERK_JWKS_URL or CLERK_ISSUER in .env
# For Clerk, it's typically https://clerk.<your-domain>.com/.well-known/jwks.json
# Or for dev: https://<your-app-id>.clerk.accounts.dev/.well-known/jwks.json

# Extracting issuer/jwks url from env or standard Clerk pattern
CLERK_ISSUER = os.getenv("CLERK_ISSUER")
if not CLERK_ISSUER and CLERK_FRONTEND_API:
    # This is a bit of a heuristic, ideally provided via env
    pass

# The TRD says: https://<your-clerk-frontend-api>/.well-known/jwks.json
# But "frontend api" usually refers to the authority.
JWKS_URL = os.getenv("CLERK_JWKS_URL")

# Global JWKS Client with caching enabled (lifespan = 1 hour)
# This prevents fetching the public keys on every request.
jwks_client = None
if JWKS_URL:
    jwks_client = PyJWKClient(JWKS_URL, cache_keys=True, cache_jwk_set=True, lifespan=3600)

security = HTTPBearer()

async def get_current_session(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Validates the Clerk JWT and extracts org_id and user_id.
    """
    token = credentials.credentials
    
    if not jwks_client:
        # Fallback for development if URL not set, though TRD requires real implementation
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="CLERK_JWKS_URL not configured"
        )

    try:
        signing_key = jwks_client.get_signing_key_from_jwt(token)

        data = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            # issuer=CLERK_ISSUER, # Optional but recommended
        )

        # Clerk JWTs contain 'org_id' and 'sub' (user_id)
        org_id = data.get("org_id")
        user_id = data.get("sub")

        if not org_id:
            # Re-verify if the user has an active org selected
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No organization selected in session"
            )

        return {
            "org_id": org_id,
            "user_id": user_id,
            "claims": data
        }
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=401, detail="Authentication failed")
