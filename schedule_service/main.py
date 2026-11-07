import hashlib
import json
import os
import socket

import redis
from fastapi import FastAPI

app = FastAPI(
    title="Schedule & QR Service API",
    docs_url="/api/schedule/docs",
    openapi_url="/api/schedule/openapi.json"
)

REDIS_HOST = os.getenv("REDIS_HOST", "redis-cache")

def get_redis_client():
    return redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)

@app.get("/api/schedule/routes")
def get_routes():
    """Получение списка маршрутов и интервалов движения с кэшированием в Redis"""
    r = get_redis_client()
    cached_routes = r.get("transport_routes")
    if cached_routes:
        return {"source": "redis_cache", "node": socket.gethostname(), "routes": json.loads(cached_routes)}

    routes = [
        {"route": "М1", "type": "Автобус", "interval_min": 5, "price": 55},
        {"route": "Трамвай 14", "type": "Трамвай", "interval_min": 8, "price": 55},
        {"route": "Линия 1", "type": "Метро", "interval_min": 2, "price": 55}
    ]
    r.setex("transport_routes", 120, json.dumps(routes))
    return {"source": "generated", "node": socket.gethostname(), "routes": routes}

@app.get("/api/schedule/qr/{ticket_id}")
def generate_qr_payload(ticket_id: str):
    """Генерация подписанного QR-токена билета для экрана мобильного приложения"""
    signature = hashlib.sha256(f"{ticket_id}-MIREA-SECRET".encode()).hexdigest()[:16]
    return {
        "ticket_id": ticket_id,
        "qr_payload": f"TRANSPORT://VERIFY/{ticket_id}?sig={signature}",
        "generated_by_node": socket.gethostname()
    }
