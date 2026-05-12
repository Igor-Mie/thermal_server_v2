import os
import time
import threading
import subprocess
import numpy as np
import cv2
from datetime import datetime
from flask import Flask, Response, jsonify, request, render_template_string

# ==========================================
# KONFIGURACJA
# ==========================================
DEVICE = "/dev/video0"
WIDTH = 160
HEIGHT = 120
FRAME_SIZE = WIDTH * HEIGHT * 2  # Y16 = 2 bajty na piksel (38400 bajtów)
ARCHIVE_DIR = "/home/avena/thermal_archive"
ARCHIVE_INTERVAL = 30.0  # Zapis na dysk co 30 sekund

# ==========================================
# STAN APLIKACJI
# ==========================================
app_state = {
    "latest_raw": None,
    "latest_time": 0.0,
    "lock": threading.Lock(),
    "running": True
}

app = Flask(__name__)
os.makedirs(ARCHIVE_DIR, exist_ok=True)

# ==========================================
# FUNKCJE POMOCNICZE
# ==========================================
def read_exactly(stream, size):
    """Odczytuje dokładnie `size` bajtów ze strumienia, zapobiegając uciętym klatkom."""
    data = b''
    while len(data) < size:
        chunk = stream.read(size - len(data))
        if not chunk:
            return None
        data += chunk
    return data

def raw_to_temp(raw_value):
    """Przelicza wartość z surowego Y16 na stopnie Celsjusza."""
    return (raw_value / 100.0) - 273.15

def create_heatmap_jpeg(raw_bytes):
    """Tworzy obraz JPEG z paletą barw na podstawie danych Y16."""
    frame_16 = np.frombuffer(raw_bytes, dtype=np.uint16).reshape((HEIGHT, WIDTH))
    
    min_val, max_val = frame_16.min(), frame_16.max()
    if max_val > min_val:
        frame_8 = ((frame_16 - min_val) / (max_val - min_val) * 255.0).astype(np.uint8)
    else:
        frame_8 = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
    
    heatmap = cv2.applyColorMap(frame_8, cv2.COLORMAP_INFERNO)
    ret, jpeg = cv2.imencode('.jpg', heatmap)
    return jpeg.tobytes() if ret else None

# ==========================================
# WĄTEK 1: CIĄGŁY ODCZYT Z KAMERY
# ==========================================
def camera_reader_thread():
    cmd = [
        "v4l2-ctl", "-d", DEVICE,
        "--set-fmt-video=width=160,height=120,pixelformat=Y16 ",
        "--stream-mmap",
        "--stream-to=-"
    ]
    
    while app_state["running"]:
        print("[KAMERA] Uruchamianie strumienia v4l2-ctl...")
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        
        try:
            while app_state["running"]:
                raw_frame = read_exactly(process.stdout, FRAME_SIZE)
                if not raw_frame:
                    print("[KAMERA] Strumień przerwany (brak danych).")
                    break
                
                with app_state["lock"]:
                    app_state["latest_raw"] = raw_frame
                    app_state["latest_time"] = time.time()
                    
        except Exception as e:
            print(f"[KAMERA] Błąd odczytu: {e}")
            
        finally:
            process.terminate()
            process.wait()
            
        if app_state["running"]:
            print("[KAMERA] Przerwa przed próbą ponownego połączenia (3s)...")
            time.sleep(3)

# ==========================================
# WĄTEK 2: ZAPIS ARCHIWUM
# ==========================================
def archive_writer_thread():
    last_save_time = 0.0
    while app_state["running"]:
        current_time = time.time()
        
        if current_time - last_save_time >= ARCHIVE_INTERVAL:
            raw_to_save = None
            frame_time = 0.0
            
            with app_state["lock"]:
                if app_state["latest_raw"] and (current_time - app_state["latest_time"] < 5.0):
                    raw_to_save = app_state["latest_raw"]
                    frame_time = app_state["latest_time"]
            
            if raw_to_save:
                dt_str = datetime.fromtimestamp(frame_time).strftime("%Y-%m-%d_%H-%M-%S")
                filename = os.path.join(ARCHIVE_DIR, f"{dt_str}.raw")
                with open(filename, 'wb') as f:
                    f.write(raw_to_save)
                print(f"[ARCHIWUM] Zapisano {filename}")
                last_save_time = current_time
                
        time.sleep(1)

# ==========================================
# ENDPOINTY FLASK
# ==========================================
@app.route('/')
def index():
    html = """
    <html>
        <head><title>PureThermal Live</title></head>
        <body style="background: #111; color: white; font-family: sans-serif; text-align: center;">
            <h2>PureThermal Live View</h2>
            <img id="thermal-img" src="/mjpeg" style="width: 640px; cursor: crosshair; border: 2px solid #555;">
            <h3 id="temp-display">Kliknij obraz aby sprawdzić temperaturę</h3>
            <script>
                document.getElementById('thermal-img').addEventListener('click', function(e) {
                    var rect = e.target.getBoundingClientRect();
                    var scaleX = 160 / rect.width;
                    var scaleY = 120 / rect.height;
                    var x = Math.floor((e.clientX - rect.left) * scaleX);
                    var y = Math.floor((e.clientY - rect.top) * scaleY);
                    
                    fetch('/temp?x=' + x + '&y=' + y)
                        .then(response => response.json())
                        .then(data => {
                            if(data.error) {
                                document.getElementById('temp-display').innerText = 'Błąd: ' + data.error;
                            } else {
                                document.getElementById('temp-display').innerText = 'Temp (' + x + ',' + y + '): ' + data.temp_c.toFixed(2) + ' °C';
                            }
                        });
                });
            </script>
        </body>
    </html>
    """
    return render_template_string(html)

@app.route('/mjpeg')
def mjpeg_stream():
    def generate():
        while True:
            raw_frame = None
            with app_state["lock"]:
                raw_frame = app_state["latest_raw"]
                
            if raw_frame:
                jpeg_bytes = create_heatmap_jpeg(raw_frame)
                if jpeg_bytes:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + jpeg_bytes + b'\r\n')
            time.sleep(0.1)
    
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/frame.jpg')
def frame_jpg():
    with app_state["lock"]:
        raw_frame = app_state["latest_raw"]
    
    if not raw_frame:
        return jsonify({"error": "Brak ramki"}), 503
        
    jpeg_bytes = create_heatmap_jpeg(raw_frame)
    return Response(jpeg_bytes, mimetype='image/jpeg')

@app.route('/temp')
def get_temp():
    x = request.args.get('x', type=int)
    y = request.args.get('y', type=int)
    
    if x is None or y is None or not (0 <= x < WIDTH) or not (0 <= y < HEIGHT):
        return jsonify({"error": "Nieprawidłowe współrzędne"}), 400
        
    with app_state["lock"]:
        raw_frame = app_state["latest_raw"]
        frame_time = app_state["latest_time"]
        
    if not raw_frame:
        return jsonify({"error": "Brak ramki"}), 503
        
    age = time.time() - frame_time
    if age > 5.0:
        return jsonify({"error": "Ramka jest zbyt stara", "age_s": round(age, 2)}), 503
        
    frame_16 = np.frombuffer(raw_frame, dtype=np.uint16).reshape((HEIGHT, WIDTH))
    pixel_raw = frame_16[y, x]
    temp_c = raw_to_temp(pixel_raw)
    
    return jsonify({
        "x": x,
        "y": y,
        "raw": int(pixel_raw),
        "temp_c": round(temp_c, 2),
        "age_s": round(age, 2)
    })

# ==========================================
# START APLIKACJI
# ==========================================
if __name__ == '__main__':
    try:
        print("[SYSTEM] Startowanie wątków tła...")
        reader_thread = threading.Thread(target=camera_reader_thread, daemon=True)
        writer_thread = threading.Thread(target=archive_writer_thread, daemon=True)
        
        reader_thread.start()
        writer_thread.start()
        
        print("[SYSTEM] Uruchamianie serwera Flask na porcie 8088...")
        app.run(host='0.0.0.0', port=8088, threaded=True)
    except KeyboardInterrupt:
        print("[SYSTEM] Zamykanie...")
        app_state["running"] = False
