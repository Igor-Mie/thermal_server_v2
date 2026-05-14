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
FRAME_SIZE = WIDTH * HEIGHT * 2
ARCHIVE_DIR = os.path.join(os.path.expanduser("~"), "thermal_archive")
ARCHIVE_INTERVAL = 30.0

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
    data = b''
    while len(data) < size:
        chunk = stream.read(size - len(data))
        if not chunk:
            return None
        data += chunk
    return data

def raw_to_temp(raw_value):
    return (raw_value / 100.0) - 273.15

def create_heatmap_jpeg(raw_bytes):
    frame_16 = np.frombuffer(raw_bytes, dtype=np.uint16).reshape((HEIGHT, WIDTH))
    min_val, max_val = frame_16.min(), frame_16.max()
    if max_val > min_val:
        frame_8 = ((frame_16 - min_val) / (max_val - min_val) * 255.0).astype(np.uint8)
    else:
        frame_8 = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
    heatmap = cv2.applyColorMap(frame_8, cv2.COLORMAP_INFERNO)
    ret, jpeg = cv2.imencode('.jpg', heatmap)
    return jpeg.tobytes() if ret else None

def get_safe_archive_path(filename):
    if not filename:
        return None
    safe_name = os.path.basename(filename)
    if not safe_name.endswith('.raw'):
        return None
    full_path = os.path.join(ARCHIVE_DIR, safe_name)
    if os.path.isfile(full_path):
        return full_path
    return None

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
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            while app_state["running"]:
                raw_frame = read_exactly(process.stdout, FRAME_SIZE)
                if not raw_frame:
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
                last_save_time = current_time
        time.sleep(1)

# ==========================================
# ENDPOINTY FLASK - LIVE
# ==========================================
@app.route('/')
def index():
    html = """
    <html>
        <head><title>PureThermal Live</title></head>
        <body style="background: #111; color: white; font-family: sans-serif; text-align: center;">
            <h2>PureThermal Live View</h2>
            <div style="margin-bottom: 20px;">
                <a href="/archive" style="color: #4CAF50; text-decoration: none; border: 1px solid #4CAF50; padding: 5px 10px; border-radius: 5px;">Przejdź do archiwum</a>
            </div>
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
                    yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + jpeg_bytes + b'\r\n')
            time.sleep(0.1)
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/temp')
def get_temp():
    x = request.args.get('x', type=int)
    y = request.args.get('y', type=int)
    if x is None or y is None or not (0 <= x < WIDTH) or not (0 <= y < HEIGHT):
        return jsonify({"error": "Nieprawidłowe współrzędne"}), 400
    
    with app_state["lock"]:
        raw_frame = app_state["latest_raw"]
        frame_time = app_state["latest_time"]
        
    if not raw_frame: return jsonify({"error": "Brak ramki"}), 503
    age = time.time() - frame_time
    if age > 5.0: return jsonify({"error": "Ramka jest zbyt stara"}), 503
        
    frame_16 = np.frombuffer(raw_frame, dtype=np.uint16).reshape((HEIGHT, WIDTH))
    pixel_raw = frame_16[y, x]
    return jsonify({"x": x, "y": y, "temp_c": round(raw_to_temp(pixel_raw), 2), "age_s": round(age, 2)})

# ==========================================
# ENDPOINTY FLASK - ARCHIWUM
# ==========================================
@app.route('/api/archives')
def list_archives():
    try:
        files = [f for f in os.listdir(ARCHIVE_DIR) if f.endswith('.raw')]
        files.sort(reverse=True)
        return jsonify(files)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/archive_frame.jpg')
def archive_frame():
    filename = request.args.get('file')
    path = get_safe_archive_path(filename)
    if not path:
        return jsonify({"error": "Plik nie istnieje"}), 404
        
    with open(path, 'rb') as f:
        raw_bytes = f.read(FRAME_SIZE)
        
    if len(raw_bytes) != FRAME_SIZE:
        return jsonify({"error": "Uszkodzony plik"}), 500
        
    jpeg_bytes = create_heatmap_jpeg(raw_bytes)
    return Response(jpeg_bytes, mimetype='image/jpeg')

@app.route('/archive_temp')
def archive_temp():
    filename = request.args.get('file')
    x = request.args.get('x', type=int)
    y = request.args.get('y', type=int)
    
    path = get_safe_archive_path(filename)
    if not path:
        return jsonify({"error": "Plik nie istnieje"}), 404
        
    if x is None or y is None or not (0 <= x < WIDTH) or not (0 <= y < HEIGHT):
        return jsonify({"error": "Nieprawidłowe współrzędne"}), 400
        
    with open(path, 'rb') as f:
        raw_bytes = f.read(FRAME_SIZE)
        
    frame_16 = np.frombuffer(raw_bytes, dtype=np.uint16).reshape((HEIGHT, WIDTH))
    pixel_raw = frame_16[y, x]
    return jsonify({"file": filename, "x": x, "y": y, "temp_c": round(raw_to_temp(pixel_raw), 2)})

@app.route('/archive')
def archive_viewer():
    html = """
    <html>
        <head>
            <title>PureThermal Archiwum</title>
            <style>
                body { background: #111; color: white; font-family: sans-serif; text-align: center; }
                #timeline { width: 640px; margin: 10px 0; cursor: pointer; }
                .btn { color: #2196F3; text-decoration: none; border: 1px solid #2196F3; padding: 5px 10px; border-radius: 5px; }
            </style>
        </head>
        <body>
            <h2>Archiwum Nagrań (Timeline)</h2>
            <div style="margin-bottom: 20px;">
                <a href="/" class="btn">Wróć do Live View</a>
            </div>
            
            <div>
                <h3 id="current-time-label" style="color: #ff9800;">Ładowanie osi czasu...</h3>
                <input type="range" id="timeline" min="0" max="0" value="0">
            </div>
            
            <img id="archive-img" style="width: 640px; cursor: crosshair; border: 2px solid #555; background: #000; min-height: 480px;">
            <h3 id="temp-display">Przesuwaj suwak, aby przeglądać klatki</h3>
            
            <script>
                let archiveFiles = [];
                const timeline = document.getElementById('timeline');
                const img = document.getElementById('archive-img');
                const tempDisplay = document.getElementById('temp-display');
                const timeLabel = document.getElementById('current-time-label');
                
                fetch('/api/archives')
                    .then(response => response.json())
                    .then(files => {
                        if(files.length === 0) {
                            timeLabel.innerText = 'Brak plików w archiwum';
                            timeline.disabled = true;
                            return;
                        }
                        
                        // API zwraca listę od najnowszego, odwracamy ją.
                        // Lewa strona suwaka (0) to najstarsze, prawa to najnowsze nagranie.
                        archiveFiles = files.reverse();
                        
                        timeline.max = archiveFiles.length - 1;
                        timeline.value = archiveFiles.length - 1; // start na najnowszej klatce
                        
                        updateImage();
                    });
                
                timeline.addEventListener('input', updateImage);
                
                function updateImage() {
                    if(archiveFiles.length === 0) return;
                    const file = archiveFiles[timeline.value];
                    
                    // Formatowanie nazwy pliku na czytelną datę
                    const readableTime = file.replace('.raw', '').replace('_', '  Godzina: ');
                    timeLabel.innerText = 'Data: ' + readableTime;
                    
                    img.src = '/archive_frame.jpg?file=' + file;
                    tempDisplay.innerText = 'Kliknij obraz, aby odczytać temperaturę';
                    
                    // Zapisujemy wybraną ramkę w dom data, żeby kliknięcie miało do niej dostęp
                    timeline.dataset.currentFile = file;
                }
                
                img.addEventListener('click', function(e) {
                    const file = timeline.dataset.currentFile;
                    if(!file) return;
                    
                    var rect = e.target.getBoundingClientRect();
                    var scaleX = 160 / rect.width;
                    var scaleY = 120 / rect.height;
                    var x = Math.floor((e.clientX - rect.left) * scaleX);
                    var y = Math.floor((e.clientY - rect.top) * scaleY);
                    
                    fetch('/archive_temp?file=' + file + '&x=' + x + '&y=' + y)
                        .then(response => response.json())
                        .then(data => {
                            if(data.error) {
                                tempDisplay.innerText = 'Błąd: ' + data.error;
                            } else {
                                tempDisplay.innerText = 'Temp (' + x + ',' + y + '): ' + data.temp_c.toFixed(2) + ' °C';
                            }
                        });
                });
            </script>
        </body>
    </html>
    """
    return render_template_string(html)

# ==========================================
# START APLIKACJI
# ==========================================
# No automatic startup
