import os
import sys
import time

import psycopg
import redis


def wait_for_services(timeout: int = 90) -> None:
    deadline = time.monotonic() + timeout
    last_error = ""

    while time.monotonic() < deadline:
        try:
            with psycopg.connect(
                dbname=os.getenv("POSTGRES_DB", "haiqu_erp"),
                user=os.getenv("POSTGRES_USER", "haiqu"),
                password=os.getenv("POSTGRES_PASSWORD", ""),
                host=os.getenv("POSTGRES_HOST", "postgres"),
                port=os.getenv("POSTGRES_PORT", "5432"),
                connect_timeout=3,
            ) as connection:
                connection.execute("SELECT 1")

            redis_client = redis.Redis.from_url(
                os.getenv("REDIS_URL", "redis://redis:6379/0"),
                socket_connect_timeout=3,
                socket_timeout=3,
            )
            redis_client.ping()

            print("PostgreSQL 和 Redis 已就绪。", flush=True)
            return
        except Exception as exc:
            last_error = f"{exc.__class__.__name__}: {exc}"
            print("等待 PostgreSQL / Redis 完全就绪...", flush=True)
            time.sleep(2)

    print(f"等待服务超时：{last_error}", file=sys.stderr, flush=True)
    raise SystemExit(1)


if __name__ == "__main__":
    wait_for_services()
