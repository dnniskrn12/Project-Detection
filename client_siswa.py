"""
=============================================================
  SISTEM DETEKSI MENGANTUK - CLIENT SISWA
  Cara pakai:
    1. pip install ultralytics opencv-python requests pillow
    2. Letakkan file best.pt di folder yang sama
    3. Jalankan: python client_siswa.py
  
  Bisa dijalankan di: Windows, Mac, Linux, Raspberry Pi
=============================================================
"""

import cv2
import time
import json
import threading
import sys
import os
import requests
from datetime import datetime
from pathlib import Path

# ─── KONFIGURASI ───────────────────────────────────────────────────────────────
# Ganti dengan URL server kamu (Railway/Render/ngrok)
SERVER_URL = "https://awakelens-detection.up.railway.app"  
# SERVER_URL = "http://localhost:8000"  # untuk testing lokal

# Path model deteksi kamu
MODEL_PATH = "best.pt"

# Interval kirim data ke server (detik)
SEND_INTERVAL = 3

# Konfigurasi kamera (0 = kamera utama, 1 = kamera kedua, dll)
CAMERA_INDEX = 0

# ─── WARNA UI ──────────────────────────────────────────────────────────────────
COLORS = {
    "awake":    (39, 174, 96),   # hijau
    "drowsy":   (230, 126, 34),  # oranye
    "sleeping": (231, 76, 60),   # merah
    "default":  (52, 73, 94),    # abu gelap
    "white":    (255, 255, 255),
    "black":    (0, 0, 0),
    "bg_dark":  (15, 20, 30),
}

# ─── CEK DEPENDENCIES ──────────────────────────────────────────────────────────
def check_dependencies():
    missing = []
    try:
        from ultralytics import YOLO
    except ImportError:
        missing.append("ultralytics")
    try:
        import cv2
    except ImportError:
        missing.append("opencv-python")
    try:
        import requests
    except ImportError:
        missing.append("requests")
    
    if missing:
        print("╔══════════════════════════════════════════╗")
        print("║  Package yang dibutuhkan belum terinstall ║")
        print("╠══════════════════════════════════════════╣")
        for pkg in missing:
            print(f"║  → pip install {pkg:<27} ║")
        print("╚══════════════════════════════════════════╝")
        sys.exit(1)

check_dependencies()

from ultralytics import YOLO

# ─── INPUT DATA SISWA ──────────────────────────────────────────────────────────
def get_student_info():
    print("\n" + "═"*50)
    print("   SISTEM DETEKSI MENGANTUK - KELAS ONLINE")
    print("═"*50)
    
    name = input("\n  Nama lengkap kamu: ").strip()
    if not name:
        name = "Anonim"
    
    student_id = input("  NIM / ID Siswa   : ").strip()
    if not student_id:
        student_id = f"STD-{int(time.time())}"
    
    class_name = input("  Nama kelas       : ").strip()
    if not class_name:
        class_name = "Kelas Umum"
    
    print("\n  ✓ Data tersimpan!")
    print(f"  Nama   : {name}")
    print(f"  ID     : {student_id}")
    print(f"  Kelas  : {class_name}")
    print("═"*50 + "\n")
    
    return name, student_id, class_name

# ─── KIRIM DATA KE SERVER ──────────────────────────────────────────────────────
def send_to_server(student_name, student_id, class_name, status, confidence):
    try:
        payload = {
            "student_name": student_name,
            "student_id": student_id,
            "class_name": class_name,
            "status": status,
            "confidence": float(confidence)
        }
        response = requests.post(
            f"{SERVER_URL}/api/detection",
            json=payload,
            timeout=5
        )
        if response.status_code == 200:
            return True
    except requests.exceptions.ConnectionError:
        print(f"  [!] Server tidak terhubung - cek URL: {SERVER_URL}")
    except Exception as e:
        print(f"  [!] Error kirim data: {e}")
    return False

# ─── GAMBAR UI OVERLAY ─────────────────────────────────────────────────────────
def draw_ui(frame, status, confidence, student_name, student_id, fps, is_connected, send_count):
    h, w = frame.shape[:2]
    
    # Warna sesuai status
    color = COLORS.get(status.lower(), COLORS["default"])
    
    # ── Header bar ──
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, 70), COLORS["bg_dark"], -1)
    cv2.addWeighted(overlay, 0.85, frame, 0.15, 0, frame)
    
    # Judul
    cv2.putText(frame, "DROWSINESS DETECTION", (15, 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, COLORS["white"], 2)
    cv2.putText(frame, f"{student_name} | {student_id}", (15, 52),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1)
    
    # FPS (kanan atas)
    fps_text = f"FPS: {fps:.0f}"
    cv2.putText(frame, fps_text, (w - 100, 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 200, 100), 1)
    
    # Status koneksi
    conn_color = (50, 200, 100) if is_connected else (200, 80, 80)
    conn_text = f"SERVER: {'ONLINE' if is_connected else 'OFFLINE'}"
    cv2.circle(frame, (w - 110, 48), 5, conn_color, -1)
    cv2.putText(frame, conn_text, (w - 100, 52),
                cv2.FONT_HERSHEY_SIMPLEX, 0.38, conn_color, 1)
    
    # ── Status box bawah ──
    box_h = 80
    overlay2 = frame.copy()
    cv2.rectangle(overlay2, (0, h - box_h), (w, h), COLORS["bg_dark"], -1)
    cv2.addWeighted(overlay2, 0.85, frame, 0.15, 0, frame)
    
    # Garis warna status
    cv2.rectangle(frame, (0, h - box_h), (w, h - box_h + 4), color, -1)
    
    # Label status besar
    status_label = {
        "awake": "AWAKE",
        "drowsy": "DROWSY!",
        "sleeping": "SLEEPING!!"
    }.get(status.lower(), status.upper())
    
    cv2.putText(frame, status_label, (20, h - 42),
                cv2.FONT_HERSHEY_SIMPLEX, 1.2, color, 3)
    
    # Confidence bar
    conf_pct = int(confidence * 100)
    bar_w = int((w - 200) * confidence)
    cv2.rectangle(frame, (20, h - 22), (w - 180, h - 10), (50, 50, 50), -1)
    cv2.rectangle(frame, (20, h - 22), (20 + bar_w, h - 10), color, -1)
    cv2.putText(frame, f"Confidence: {conf_pct}%", (w - 170, h - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1)
    
    # Send count
    cv2.putText(frame, f"Terkirim: {send_count}x", (20, h - 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (120, 120, 120), 1)
    
    # Timestamp
    ts = datetime.now().strftime("%H:%M:%S")
    cv2.putText(frame, ts, (w - 90, h - 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (120, 120, 120), 1)
    
    # Warning overlay jika mengantuk/tidur
    if status.lower() in ["drowsy", "sleeping"]:
        alpha = 0.12 if status.lower() == "drowsy" else 0.25
        warning = frame.copy()
        cv2.rectangle(warning, (0, 70), (w, h - box_h), color, -1)
        cv2.addWeighted(warning, alpha, frame, 1 - alpha, 0, frame)
    
    return frame

# ─── MAIN PROGRAM ──────────────────────────────────────────────────────────────
def main():
    student_name, student_id, class_name = get_student_info()
    
    # Cek model
    if not Path(MODEL_PATH).exists():
        print(f"  [!] File model '{MODEL_PATH}' tidak ditemukan!")
        print(f"  → Letakkan file best.pt di: {Path('.').absolute()}")
        sys.exit(1)
    
    print("  Memuat model AI...")
    try:
        model = YOLO(MODEL_PATH)
        print(f"  ✓ Model '{MODEL_PATH}' berhasil dimuat!")
    except Exception as e:
        print(f"  [!] Gagal memuat model: {e}")
        sys.exit(1)
    
    # Buka kamera
    print(f"  Membuka kamera {CAMERA_INDEX}...")
    cap = cv2.VideoCapture(CAMERA_INDEX)
    
    if not cap.isOpened():
        print("  [!] Kamera tidak bisa dibuka!")
        print("  → Coba ganti CAMERA_INDEX = 1 atau 2")
        sys.exit(1)
    
    # Set resolusi
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    
    print("  ✓ Kamera aktif!")
    print("\n  ► Tekan Q untuk keluar")
    print("═"*50 + "\n")
    
    # State variabel
    current_status = "awake"
    current_confidence = 0.0
    is_connected = False
    send_count = 0
    last_send_time = 0
    fps_counter = 0
    fps_start = time.time()
    fps = 0
    
    # Thread untuk kirim data
    send_lock = threading.Lock()
    send_queue = {"status": "awake", "confidence": 0.0, "pending": False}
    
    def sender_thread():
        nonlocal is_connected, send_count
        while True:
            with send_lock:
                if send_queue["pending"]:
                    s = send_queue["status"]
                    c = send_queue["confidence"]
                    send_queue["pending"] = False
                else:
                    time.sleep(0.1)
                    continue
            
            ok = send_to_server(student_name, student_id, class_name, s, c)
            is_connected = ok
            if ok:
                send_count += 1
            time.sleep(0.05)
    
    t = threading.Thread(target=sender_thread, daemon=True)
    t.start()
    
    while True:
        ret, frame = cap.read()
        if not ret:
            print("  [!] Gagal baca frame kamera")
            break
        
        # FPS hitung
        fps_counter += 1
        if time.time() - fps_start >= 1.0:
            fps = fps_counter / (time.time() - fps_start)
            fps_counter = 0
            fps_start = time.time()
        
        # ── DETEKSI MODEL ──
        results = model(frame, conf=0.35, verbose=False)
        
        best_status = "awake"
        best_conf = 0.0
        
        for result in results:
            boxes = result.boxes
            if boxes is not None:
                for box in boxes:
                    conf = float(box.conf[0])
                    cls_id = int(box.cls[0])
                    cls_name = model.names[cls_id].lower()
                    
                    # Gambar bounding box
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    label_color = COLORS.get(cls_name, COLORS["default"])
                    
                    cv2.rectangle(frame, (x1, y1), (x2, y2), label_color, 2)
                    
                    label_text = f"{cls_name.upper()} {conf:.0%}"
                    label_bg_y = max(y1 - 30, 75)
                    cv2.rectangle(frame, (x1, label_bg_y), 
                                  (x1 + len(label_text) * 11, label_bg_y + 22),
                                  label_color, -1)
                    cv2.putText(frame, label_text, (x1 + 4, label_bg_y + 15),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLORS["white"], 1)
                    
                    # Ambil deteksi dengan confidence tertinggi
                    if conf > best_conf:
                        best_conf = conf
                        best_status = cls_name
        
        current_status = best_status
        current_confidence = best_conf
        
        # ── KIRIM DATA KE SERVER ──
        now = time.time()
        if now - last_send_time >= SEND_INTERVAL:
            with send_lock:
                send_queue["status"] = current_status
                send_queue["confidence"] = current_confidence
                send_queue["pending"] = True
            last_send_time = now
        
        # ── GAMBAR UI ──
        frame = draw_ui(
            frame, current_status, current_confidence,
            student_name, student_id, fps, is_connected, send_count
        )
        
        # Tampilkan
        cv2.imshow("Drowsiness Detection - Tekan Q untuk keluar", frame)
        
        # Quit
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q') or key == ord('Q') or key == 27:
            break
    
    # Cleanup
    cap.release()
    cv2.destroyAllWindows()
    
    # Kirim status offline
    send_to_server(student_name, student_id, class_name, "offline", 0.0)
    print("\n  ✓ Program selesai. Data offline terkirim.")

if __name__ == "__main__":
    main()
