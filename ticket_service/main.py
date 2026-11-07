import json
import os
import socket
import uuid

import pika
import psycopg2
import redis
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(
    title="Ticket Service API (Mobile Integration)",
    docs_url="/api/tickets/docs",
    openapi_url="/api/tickets/openapi.json"
)

DB_HOST = os.getenv("DB_HOST", "postgres-db")
DB_NAME = os.getenv("DB_NAME", "tickets_db")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "postgres")
REDIS_HOST = os.getenv("REDIS_HOST", "redis-cache")
RABBIT_HOST = os.getenv("RABBIT_HOST", "rabbitmq")

class TicketRequest(BaseModel):
    user_phone: str
    route_number: str
    transport_type: str
    price: int = 55

def get_db_connection():
    conn = psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS)
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                ticket_id VARCHAR(50) PRIMARY KEY,
                user_phone VARCHAR(20),
                route_number VARCHAR(20),
                transport_type VARCHAR(20),
                price INT,
                status VARCHAR(20)
            );
        """)
        conn.commit()
    return conn

def get_redis_client():
    return redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)

def send_push_notification(payload: dict):
    try:
        connection = pika.BlockingConnection(pika.ConnectionParameters(host=RABBIT_HOST))
        channel = connection.channel()
        channel.queue_declare(queue="mobile_push_queue", durable=True)
        channel.basic_publish(
            exchange="",
            routing_key="mobile_push_queue",
            body=json.dumps(payload)
        )
        connection.close()
    except Exception as e:
        print(f"RabbitMQ warning: {e}")

@app.get("/api/tickets/health")
def health_check():
    """Возвращает ID контейнера для демонстрации балансировки в кластере"""
    return {
        "service": "ticket-service",
        "status": "ok",
        "container_id": socket.gethostname()
    }

@app.post("/api/tickets/buy")
def buy_ticket(req: TicketRequest):
    """Покупка билета из мобильного приложения"""
    ticket_id = f"TKT-{uuid.uuid4().hex[:8].upper()}"
    
    # 1. Сохраняем билет в PostgreSQL
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO tickets VALUES (%s, %s, %s, %s, %s, %s)",
            (ticket_id, req.user_phone, req.route_number, req.transport_type, req.price, "ACTIVE")
        )
        conn.commit()
    conn.close()

    ticket_data = {
        "ticket_id": ticket_id,
        "user_phone": req.user_phone,
        "route_number": req.route_number,
        "transport_type": req.transport_type,
        "price": req.price,
        "status": "ACTIVE",
        "processed_by_node": socket.gethostname()
    }

    # 2. Кэшируем активный билет в Redis для быстрой проверки на турникете
    r = get_redis_client()
    r.setex(f"ticket:{ticket_id}", 3600, json.dumps(ticket_data))

    # 3. Отправляем событие в RabbitMQ для push-уведомления в приложение
    send_push_notification({"event": "TICKET_BOUGHT", "ticket": ticket_data})

    return ticket_data

@app.get("/api/tickets/{ticket_id}")
def verify_ticket(ticket_id: str):
    """Проверка статуса билета (сначала в Redis, затем в PostgreSQL)"""
    r = get_redis_client()
    cached = r.get(f"ticket:{ticket_id}")
    if cached:
        data = json.loads(cached)
        data["source"] = "redis_cache"
        return data

    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT ticket_id, user_phone, route_number, transport_type, price, status FROM tickets WHERE ticket_id = %s", (ticket_id,))
        row = cur.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Билет не найден")

    return {
        "ticket_id": row[0],
        "user_phone": row[1],
        "route_number": row[2],
        "transport_type": row[3],
        "price": row[4],
        "status": row[5],
        "source": "postgresql_db"
    }
