from redis.asyncio import Redis
import os
from config import REDIS_URL

redis = Redis.from_url(
    REDIS_URL,
    decode_responses=True  # importante → strings en vez de bytes
)
