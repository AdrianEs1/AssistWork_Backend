from contextlib import asynccontextmanager
import time

@asynccontextmanager
async def timer(label: str):
    start = time.perf_counter()
    yield
    print(f"⏱️ {label}: {time.perf_counter() - start:.3f}s")