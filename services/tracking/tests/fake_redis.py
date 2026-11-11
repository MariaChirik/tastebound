import redis


class FakeRedis:
    def __init__(self, down=False):
        self.data = {}
        self.down = down
        self.ttl = {}

    def _check(self):
        if self.down:
            raise redis.RedisError("connection refused")

    def ping(self):
        self._check()
        return True

    def hset(self, key, field=None, value=None, mapping=None):
        self._check()
        bucket = self.data.setdefault(key, {})
        if mapping is not None:
            bucket.update({k: str(v) for k, v in mapping.items()})
        else:
            bucket[field] = str(value)

    def hget(self, key, field):
        return self.data.get(key, {}).get(field)

    def hgetall(self, key):
        self._check()
        return dict(self.data.get(key, {}))

    def exists(self, key):
        return int(key in self.data)

    def expire(self, key, seconds):
        self.ttl[key] = seconds

    def sadd(self, key, value):
        self.data.setdefault(key, set()).add(value)

    def smembers(self, key):
        return set(self.data.get(key, set()))

    def rpush(self, key, value):
        self._check()
        self.data.setdefault(key, []).append(value)

    def lpush(self, key, value):
        self.data.setdefault(key, []).insert(0, value)

    def lpop(self, key):
        items = self.data.get(key, [])
        return items.pop(0) if items else None

    def blpop(self, key, timeout=0):
        value = self.lpop(key)
        return None if value is None else (key, value)

    def llen(self, key):
        return len(self.data.get(key, []))

    def lrange(self, key, start, end):
        items = self.data.get(key, [])
        return items[start:] if end == -1 else items[start:end + 1]

    def ltrim(self, key, start, end):
        self.data[key] = self.lrange(key, start, end)
