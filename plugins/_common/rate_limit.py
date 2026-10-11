# -*- coding: utf-8 -*-
from __future__ import annotations

import threading
import time
from collections import deque


class TokenBucket:
    def __init__(self, rate: float = 2.0, burst: int = 4):
        self.rate = rate
        self.burst = burst
        self.tokens = float(burst)
        self.updated = time.monotonic()
        self.lock = threading.Lock()
        self.recent = deque(maxlen=50)

    def acquire(self, timeout: float = 20.0) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.burst, self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    self.recent.append(now)
                    return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.15)


SUPPLIER_BUCKET = TokenBucket(rate=1.5, burst=3)
FUNPAY_BUCKET = TokenBucket(rate=1.0, burst=2)
