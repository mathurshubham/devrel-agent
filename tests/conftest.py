import pytest
import os

# Satisfy the Fernet 64-hex-char startup validation
os.environ["ENCRYPTION_SECRET"] = "0" * 64

@pytest.fixture
def mock_redis():
    class MockRedis:
        async def get(self, key):
            return None
        async def set(self, key, value, nx=False, px=None):
            return True
        async def zremrangebyscore(self, *args, **kwargs):
            pass
        async def zcard(self, *args, **kwargs):
            return 0
        async def zadd(self, *args, **kwargs):
            pass
        async def expire(self, *args, **kwargs):
            pass
    return MockRedis()
