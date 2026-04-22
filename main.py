"""
=============================================================
  SISTEM DETEKSI MENGANTUK - SERVER FASTAPI
  Jalankan: uvicorn main:app --host 0.0.0.0 --port 8000
  Deploy gratis: Railway.app 
=============================================================
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from datetime import datetime
import sqlite3
import json
import asyncio
from typing import List, Optional
import os

app = FastAPI(title="Drowsiness Detection Server", version="1.0.0")

# CORS - izinkan semua origin agar client manapun bisa connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── DATABASE SETUP ────────────────────────────────────────────────────────────
DB_PATH = "drowsiness.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_name TEXT NOT NULL,
            student_id TEXT NOT NULL,
            class_name TEXT,
            status TEXT NOT NULL,
            confidence REAL,
            timestamp TEXT NOT NULL,
            ip_address TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS students (
            student_id TEXT PRIMARY KEY,
            student_name TEXT NOT NULL,
            class_name TEXT,
            last_seen TEXT,
            current_status TEXT DEFAULT 'offline'
        )
    """)
    conn.commit()
    conn.close()

init_db()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ─── WEBSOCKET MANAGER ─────────────────────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        dead = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                dead.append(connection)
        for d in dead:
            self.disconnect(d)

manager = ConnectionManager()

# ─── MODELS ────────────────────────────────────────────────────────────────────
class DetectionData(BaseModel):
    student_name: str
    student_id: str
    class_name: Optional[str] = "Kelas Umum"
    status: str           # "awake", "drowsy", "sleeping"
    confidence: Optional[float] = 0.0
    ip_address: Optional[str] = ""

class StudentResponse(BaseModel):
    student_id: str
    student_name: str
    class_name: str
    current_status: str
    last_seen: str

# ─── ENDPOINTS ─────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "message": "Drowsiness Detection Server is running!",
        "version": "1.0.0",
        "endpoints": {
            "post_detection": "POST /api/detection",
            "get_students": "GET /api/students",
            "get_logs": "GET /api/logs",
            "websocket": "WS /ws/dashboard",
            "dashboard": "GET /dashboard"
        }
    }

@app.post("/api/detection")
async def receive_detection(data: DetectionData, request_ip: str = ""):
    """Endpoint utama: terima data deteksi dari client Python siswa"""
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Simpan ke database
    conn = get_db()
    cursor = conn.cursor()
    
    # Upsert data student
    cursor.execute("""
        INSERT INTO students (student_id, student_name, class_name, last_seen, current_status)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(student_id) DO UPDATE SET
            student_name=excluded.student_name,
            class_name=excluded.class_name,
            last_seen=excluded.last_seen,
            current_status=excluded.current_status
    """, (data.student_id, data.student_name, data.class_name, timestamp, data.status))
    
    # Simpan log deteksi
    cursor.execute("""
        INSERT INTO sessions (student_name, student_id, class_name, status, confidence, timestamp, ip_address)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (data.student_name, data.student_id, data.class_name, 
          data.status, data.confidence, timestamp, data.ip_address))
    
    conn.commit()
    conn.close()
    
    # Broadcast ke semua dashboard yang terhubung via WebSocket
    broadcast_data = {
        "type": "detection_update",
        "student_name": data.student_name,
        "student_id": data.student_id,
        "class_name": data.class_name,
        "status": data.status,
        "confidence": round(data.confidence * 100, 1),
        "timestamp": timestamp
    }
    await manager.broadcast(broadcast_data)
    
    return {
        "success": True,
        "message": f"Status '{data.status}' dari {data.student_name} diterima",
        "timestamp": timestamp
    }

@app.get("/api/students")
async def get_students():
    """Ambil daftar semua siswa beserta status terkini"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM students ORDER BY last_seen DESC")
    rows = cursor.fetchall()
    conn.close()
    return {"students": [dict(r) for r in rows]}

@app.get("/api/logs")
async def get_logs(limit: int = 100, student_id: Optional[str] = None):
    """Ambil log deteksi"""
    conn = get_db()
    cursor = conn.cursor()
    if student_id:
        cursor.execute(
            "SELECT * FROM sessions WHERE student_id=? ORDER BY id DESC LIMIT ?",
            (student_id, limit)
        )
    else:
        cursor.execute("SELECT * FROM sessions ORDER BY id DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return {"logs": [dict(r) for r in rows]}

@app.get("/api/stats")
async def get_stats():
    """Statistik ringkasan"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT current_status, COUNT(*) as count FROM students GROUP BY current_status")
    rows = cursor.fetchall()
    conn.close()
    stats = {"awake": 0, "drowsy": 0, "sleeping": 0, "offline": 0}
    for r in rows:
        stats[r["current_status"]] = r["count"]
    return stats

@app.delete("/api/reset")
async def reset_data():
    """Reset semua data (untuk testing)"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM students")
    cursor.execute("DELETE FROM sessions")
    conn.commit()
    conn.close()
    await manager.broadcast({"type": "reset"})
    return {"success": True, "message": "Data berhasil direset"}

# ─── WEBSOCKET ─────────────────────────────────────────────────────────────────
@app.websocket("/ws/dashboard")
async def websocket_dashboard(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # Kirim data awal saat dashboard terhubung
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM students ORDER BY last_seen DESC")
        students = [dict(r) for r in cursor.fetchall()]
        conn.close()
        
        await websocket.send_json({
            "type": "initial_data",
            "students": students
        })
        
        # Keep alive loop
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        manager.disconnect(websocket)

# ─── DASHBOARD HTML (embedded) ──────────────────────────────────────────────────
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Dashboard monitoring untuk dosen - bisa diakses langsung di browser"""
    html_content = open("dashboard.html").read() if os.path.exists("dashboard.html") else "<h1>Dashboard file tidak ditemukan. Letakkan dashboard.html di folder yang sama.</h1>"
    return HTMLResponse(content=html_content)
