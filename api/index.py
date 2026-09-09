from http.server import BaseHTTPRequestHandler
import json
import urllib.parse
from datetime import datetime, timezone
import threading
import os
import uuid
import sqlite3
import math
import csv
import io

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML_PATH = os.path.join(BASE_DIR, 'public', 'index.html') if os.path.exists(os.path.join(BASE_DIR, 'public', 'index.html')) else os.path.join(BASE_DIR, 'em.html')
ADMIN_PATH = os.path.join(BASE_DIR, 'public', 'admin.html') if os.path.exists(os.path.join(BASE_DIR, 'public', 'admin.html')) else os.path.join(BASE_DIR, 'admin.html')

# In Vercel / serverless lambda environment, /tmp is the writable storage directory
if os.environ.get('VERCEL') or os.environ.get('AWS_LAMBDA_FUNCTION_NAME') or not os.access(BASE_DIR, os.W_OK):
    DB_PATH = '/tmp/geotrace.db'
else:
    DB_PATH = os.path.join(BASE_DIR, 'geotrace.db')

db_lock = threading.Lock()

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db_lock:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('PRAGMA journal_mode = WAL;')
        
        # Campaigns table
        c.execute('''
            CREATE TABLE IF NOT EXISTS campaigns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                template TEXT DEFAULT 'default',
                redirect_url TEXT,
                created_at TEXT NOT NULL
            )
        ''')
        
        # Sessions / Consent table
        c.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                campaign_code TEXT,
                ip_address TEXT,
                user_agent TEXT,
                origin TEXT,
                browser TEXT,
                os TEXT,
                device_type TEXT,
                screen_res TEXT,
                viewport TEXT,
                pixel_ratio TEXT,
                language TEXT,
                timezone TEXT,
                cpu_cores TEXT,
                gpu_vendor TEXT,
                gpu_renderer TEXT,
                battery_level REAL,
                battery_charging INTEGER,
                connection_type TEXT,
                connection_downlink REAL,
                created_at TEXT NOT NULL,
                last_active TEXT NOT NULL
            )
        ''')
        
        # Locations telemetry table
        c.execute('''
            CREATE TABLE IF NOT EXISTS locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                accuracy REAL,
                altitude REAL,
                heading REAL,
                speed REAL,
                battery_level REAL,
                network_type TEXT,
                raw_data_json TEXT,
                FOREIGN KEY (token) REFERENCES sessions (token) ON DELETE CASCADE
            )
        ''')
        
        # Default campaigns if none exist
        c.execute('SELECT COUNT(*) as cnt FROM campaigns')
        if c.fetchone()['cnt'] == 0:
            now = datetime.now(timezone.utc).isoformat()
            c.execute('INSERT INTO campaigns (code, name, template, created_at) VALUES (?, ?, ?, ?)',
                      ('default', 'General Public Link', 'default', now))
            c.execute('INSERT INTO campaigns (code, name, template, created_at) VALUES (?, ?, ?, ?)',
                      ('weather', 'Live Weather Radar Preview', 'weather', now))
            c.execute('INSERT INTO campaigns (code, name, template, created_at) VALUES (?, ?, ?, ?)',
                      ('speedtest', 'Network Speed & Latency Test', 'speedtest', now))
            c.execute('INSERT INTO campaigns (code, name, template, created_at) VALUES (?, ?, ?, ?)',
                      ('download', 'Cloud Secure File Share', 'download', now))

        conn.commit()
        conn.close()

# Auto-initialize database schema
init_db()

def haversine_distance(lat1, lon1, lat2, lon2):
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return 0.0
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2.0) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2.0) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c

class handler(BaseHTTPRequestHandler):
    def _send_response(self, status_code=200, content_type='application/json', extra_headers=None):
        self.send_response(status_code)
        self.send_header('Content-Type', content_type)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()

    def do_OPTIONS(self):
        self._send_response(200)

    def do_GET(self):
        try:
            init_db()
            parsed_url = urllib.parse.urlparse(self.path)
            raw_path = parsed_url.path
            query_params = urllib.parse.parse_qs(parsed_url.query)

            # Strip '/api' prefix to normalize both /api/sessions and /sessions
            norm_path = raw_path
            if norm_path.startswith('/api/'):
                norm_path = '/' + norm_path[5:]

            # Serve HTML views
            if raw_path in ('/', '/index.html') or norm_path in ('/', '/index.html'):
                if os.path.exists(HTML_PATH):
                    with open(HTML_PATH, 'rb') as f:
                        html = f.read()
                    self._send_response(200, content_type='text/html; charset=utf-8')
                    self.wfile.write(html)
                    return

            if raw_path in ('/admin', '/admin.html') or norm_path in ('/admin', '/admin.html'):
                if os.path.exists(ADMIN_PATH):
                    with open(ADMIN_PATH, 'rb') as f:
                        html = f.read()
                    self._send_response(200, content_type='text/html; charset=utf-8')
                    self.wfile.write(html)
                    return

            # API: Stats (/api/stats or /stats)
            if raw_path == '/api/stats' or norm_path == '/stats':
                with db_lock:
                    conn = get_db_connection()
                    c = conn.cursor()
                    c.execute('SELECT COUNT(*) as total_sessions FROM sessions')
                    total_sessions = c.fetchone()['total_sessions']
                    c.execute('SELECT COUNT(*) as total_locations FROM locations')
                    total_locations = c.fetchone()['total_locations']
                    c.execute('SELECT COUNT(*) as total_campaigns FROM campaigns')
                    total_campaigns = c.fetchone()['total_campaigns']
                    conn.close()
                self._send_response()
                self.wfile.write(json.dumps({
                    'total_sessions': total_sessions,
                    'total_locations': total_locations,
                    'total_campaigns': total_campaigns
                }).encode('utf-8'))
                return

            # API: Campaigns (/api/campaigns or /campaigns)
            if raw_path == '/api/campaigns' or norm_path == '/campaigns':
                with db_lock:
                    conn = get_db_connection()
                    c = conn.cursor()
                    c.execute('SELECT * FROM campaigns ORDER BY id DESC')
                    rows = [dict(r) for r in c.fetchall()]
                    conn.close()
                self._send_response()
                self.wfile.write(json.dumps(rows).encode('utf-8'))
                return

            # API: Sessions List (/api/sessions or /sessions)
            if raw_path == '/api/sessions' or norm_path == '/sessions':
                with db_lock:
                    conn = get_db_connection()
                    c = conn.cursor()
                    c.execute('''
                        SELECT s.*, 
                               COUNT(l.id) as location_count,
                               MAX(l.timestamp) as latest_fix,
                               (SELECT latitude FROM locations WHERE token = s.token ORDER BY id DESC LIMIT 1) as latest_lat,
                               (SELECT longitude FROM locations WHERE token = s.token ORDER BY id DESC LIMIT 1) as latest_lon,
                               (SELECT accuracy FROM locations WHERE token = s.token ORDER BY id DESC LIMIT 1) as latest_acc,
                               (SELECT speed FROM locations WHERE token = s.token ORDER BY id DESC LIMIT 1) as latest_speed
                        FROM sessions s
                        LEFT JOIN locations l ON s.token = l.token
                        GROUP BY s.token
                        ORDER BY s.last_active DESC
                    ''')
                    sessions = [dict(r) for r in c.fetchall()]

                    for sess in sessions:
                        c.execute('SELECT latitude, longitude FROM locations WHERE token = ? ORDER BY id ASC', (sess['token'],))
                        locs = c.fetchall()
                        dist = 0.0
                        for i in range(len(locs) - 1):
                            dist += haversine_distance(locs[i]['latitude'], locs[i]['longitude'],
                                                       locs[i+1]['latitude'], locs[i+1]['longitude'])
                        sess['total_distance_km'] = round(dist, 4)
                        sess['total_distance_m'] = round(dist * 1000, 1)

                    conn.close()
                self._send_response()
                self.wfile.write(json.dumps(sessions).encode('utf-8'))
                return

            # API: Single Session details (/api/sessions/<token> or /sessions/<token>)
            if raw_path.startswith('/api/sessions/') or norm_path.startswith('/sessions/'):
                token = raw_path.split('/api/sessions/')[1] if '/api/sessions/' in raw_path else norm_path.split('/sessions/')[1]
                with db_lock:
                    conn = get_db_connection()
                    c = conn.cursor()
                    c.execute('SELECT * FROM sessions WHERE token = ?', (token,))
                    sess_row = c.fetchone()
                    if not sess_row:
                        conn.close()
                        self._send_response(404)
                        self.wfile.write(json.dumps({'error': 'Session not found'}).encode('utf-8'))
                        return
                    sess_data = dict(sess_row)
                    c.execute('SELECT * FROM locations WHERE token = ? ORDER BY id ASC', (token,))
                    locations = [dict(r) for r in c.fetchall()]
                    conn.close()

                dist = 0.0
                for i in range(len(locations) - 1):
                    d = haversine_distance(locations[i]['latitude'], locations[i]['longitude'],
                                           locations[i+1]['latitude'], locations[i+1]['longitude'])
                    dist += d
                    locations[i+1]['step_distance_m'] = round(d * 1000, 2)
                if locations:
                    locations[0]['step_distance_m'] = 0.0
                sess_data['locations'] = locations
                sess_data['total_distance_km'] = round(dist, 4)
                sess_data['total_distance_m'] = round(dist * 1000, 1)

                self._send_response()
                self.wfile.write(json.dumps(sess_data).encode('utf-8'))
                return

            # API: Locations (/api/locations or /locations)
            if raw_path == '/api/locations' or norm_path == '/locations':
                limit = int(query_params.get('limit', [1000])[0])
                token = query_params.get('token', [None])[0]
                with db_lock:
                    conn = get_db_connection()
                    c = conn.cursor()
                    if token:
                        c.execute('SELECT * FROM locations WHERE token = ? ORDER BY id ASC LIMIT ?', (token, limit))
                    else:
                        c.execute('SELECT * FROM locations ORDER BY id DESC LIMIT ?', (limit,))
                    rows = [dict(r) for r in c.fetchall()]
                    conn.close()
                self._send_response()
                self.wfile.write(json.dumps(rows).encode('utf-8'))
                return

            # API: Export (/api/export or /export)
            if raw_path == '/api/export' or norm_path == '/export':
                fmt = query_params.get('format', ['json'])[0].lower()
                token = query_params.get('session', [None])[0]
                
                with db_lock:
                    conn = get_db_connection()
                    c = conn.cursor()
                    if token:
                        c.execute('SELECT * FROM sessions WHERE token = ?', (token,))
                        sess_rows = [dict(r) for r in c.fetchall()]
                        c.execute('SELECT * FROM locations WHERE token = ? ORDER BY id ASC', (token,))
                        loc_rows = [dict(r) for r in c.fetchall()]
                    else:
                        c.execute('SELECT * FROM sessions ORDER BY created_at ASC')
                        sess_rows = [dict(r) for r in c.fetchall()]
                        c.execute('SELECT * FROM locations ORDER BY id ASC')
                        loc_rows = [dict(r) for r in c.fetchall()]
                    conn.close()

                timestamp_str = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
                filename_base = f"geotrace_export_{token or 'all'}_{timestamp_str}"

                if fmt == 'geojson':
                    features = []
                    grouped_locs = {}
                    for l in loc_rows:
                        grouped_locs.setdefault(l['token'], []).append(l)

                    for l in loc_rows:
                        features.append({
                            'type': 'Feature',
                            'geometry': {
                                'type': 'Point',
                                'coordinates': [l['longitude'], l['latitude'], l['altitude'] or 0.0]
                            },
                            'properties': {
                                'id': l['id'],
                                'token': l['token'],
                                'timestamp': l['timestamp'],
                                'accuracy': l['accuracy'],
                                'speed': l['speed'],
                                'heading': l['heading'],
                                'battery_level': l['battery_level'],
                                'network_type': l['network_type']
                            }
                        })

                    for sess_token, pts in grouped_locs.items():
                        if len(pts) > 1:
                            features.append({
                                'type': 'Feature',
                                'geometry': {
                                    'type': 'LineString',
                                    'coordinates': [[p['longitude'], p['latitude'], p['altitude'] or 0.0] for p in pts]
                                },
                                'properties': {
                                    'token': sess_token,
                                    'point_count': len(pts),
                                    'start_time': pts[0]['timestamp'],
                                    'end_time': pts[-1]['timestamp']
                                }
                            })

                    geojson_doc = {
                        'type': 'FeatureCollection',
                        'generator': 'GEOTRACE-Linker-Vercel',
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'features': features
                    }
                    extra = {'Content-Disposition': f'attachment; filename="{filename_base}.geojson"'}
                    self._send_response(200, content_type='application/geo+json', extra_headers=extra)
                    self.wfile.write(json.dumps(geojson_doc, indent=2).encode('utf-8'))
                    return

                if fmt == 'csv':
                    output = io.StringIO()
                    writer = csv.writer(output)
                    writer.writerow([
                        'location_id', 'session_token', 'campaign_code', 'timestamp',
                        'latitude', 'longitude', 'accuracy_m', 'altitude_m', 'heading_deg', 'speed_mps',
                        'battery_level', 'network_type', 'ip_address', 'browser', 'os', 'device_type'
                    ])
                    sess_map = {s['token']: s for s in sess_rows}
                    for l in loc_rows:
                        s = sess_map.get(l['token'], {})
                        writer.writerow([
                            l['id'], l['token'], s.get('campaign_code', ''), l['timestamp'],
                            l['latitude'], l['longitude'], l['accuracy'], l['altitude'], l['heading'], l['speed'],
                            l['battery_level'], l['network_type'], s.get('ip_address', ''),
                            s.get('browser', ''), s.get('os', ''), s.get('device_type', '')
                        ])
                    extra = {'Content-Disposition': f'attachment; filename="{filename_base}.csv"'}
                    self._send_response(200, content_type='text/csv; charset=utf-8', extra_headers=extra)
                    self.wfile.write(output.getvalue().encode('utf-8'))
                    return

                payload = {
                    'exported_at': datetime.now(timezone.utc).isoformat(),
                    'sessions': sess_rows,
                    'locations': loc_rows
                }
                extra = {'Content-Disposition': f'attachment; filename="{filename_base}.json"'}
                self._send_response(200, content_type='application/json', extra_headers=extra)
                self.wfile.write(json.dumps(payload, indent=2).encode('utf-8'))
                return

            self._send_response(404)
            self.wfile.write(json.dumps({'error': 'Endpoint not found', 'path': raw_path}).encode('utf-8'))

        except Exception as e:
            self._send_response(500)
            self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))

    def do_POST(self):
        try:
            init_db()
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            raw_path = urllib.parse.urlparse(self.path).path
            data = json.loads(post_data or '{}')

            norm_path = raw_path
            if norm_path.startswith('/api/'):
                norm_path = '/' + norm_path[5:]

            # Create Campaign
            if raw_path == '/api/campaigns' or norm_path == '/campaigns':
                code = (data.get('code') or '').strip().lower()
                name = (data.get('name') or '').strip()
                template = data.get('template') or 'default'
                redirect_url = data.get('redirect_url') or None
                if not code or not name:
                    self._send_response(400)
                    self.wfile.write(json.dumps({'error': 'Code and name are required'}).encode('utf-8'))
                    return

                now = datetime.now(timezone.utc).isoformat()
                with db_lock:
                    conn = get_db_connection()
                    c = conn.cursor()
                    try:
                        c.execute('''
                            INSERT INTO campaigns (code, name, template, redirect_url, created_at)
                            VALUES (?, ?, ?, ?, ?)
                        ''', (code, name, template, redirect_url, now))
                        conn.commit()
                        new_id = c.lastrowid
                    except sqlite3.IntegrityError:
                        conn.close()
                        self._send_response(409)
                        self.wfile.write(json.dumps({'error': 'Campaign code already exists'}).encode('utf-8'))
                        return
                    conn.close()

                self._send_response(201)
                self.wfile.write(json.dumps({'status': 'created', 'id': new_id, 'code': code}).encode('utf-8'))
                return

            # Register Consent & Fingerprint (/consent or /api/consent)
            if raw_path in ('/consent', '/api/consent') or norm_path in ('/consent', '/api/consent'):
                consent = bool(data.get('consent', True))
                if not consent:
                    self._send_response(400)
                    self.wfile.write(json.dumps({'error': 'Consent required'}).encode('utf-8'))
                    return

                token = data.get('token') or str(uuid.uuid4())
                campaign_code = data.get('campaign_code') or data.get('campaign') or 'default'
                
                client_ip = (
                    self.headers.get('X-Forwarded-For', '').split(',')[0].strip() or
                    self.headers.get('X-Real-IP') or
                    getattr(self, 'client_address', ['127.0.0.1'])[0]
                )
                if data.get('client_ip'):
                    client_ip = data.get('client_ip')

                now = datetime.now(timezone.utc).isoformat()

                with db_lock:
                    conn = get_db_connection()
                    c = conn.cursor()
                    c.execute('''
                        INSERT INTO sessions (
                            token, campaign_code, ip_address, user_agent, origin,
                            browser, os, device_type, screen_res, viewport, pixel_ratio,
                            language, timezone, cpu_cores, gpu_vendor, gpu_renderer,
                            battery_level, battery_charging, connection_type, connection_downlink,
                            created_at, last_active
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(token) DO UPDATE SET
                            last_active = excluded.last_active,
                            battery_level = COALESCE(excluded.battery_level, sessions.battery_level),
                            battery_charging = COALESCE(excluded.battery_charging, sessions.battery_charging),
                            connection_type = COALESCE(excluded.connection_type, sessions.connection_type)
                    ''', (
                        token,
                        campaign_code,
                        client_ip,
                        self.headers.get('User-Agent', data.get('user_agent')),
                        self.headers.get('Origin', data.get('origin')),
                        data.get('browser'),
                        data.get('os'),
                        data.get('device_type'),
                        data.get('screen_res'),
                        data.get('viewport'),
                        str(data.get('pixel_ratio', '')),
                        data.get('language'),
                        data.get('timezone'),
                        str(data.get('cpu_cores', '')),
                        data.get('gpu_vendor'),
                        data.get('gpu_renderer'),
                        data.get('battery_level'),
                        1 if data.get('battery_charging') else 0,
                        data.get('connection_type'),
                        data.get('connection_downlink'),
                        now,
                        now
                    ))
                    conn.commit()
                    conn.close()

                self._send_response()
                self.wfile.write(json.dumps({'status': 'consent_recorded', 'token': token}).encode('utf-8'))
                return

            # Submit Location Fix (/submit-location or /api/submit-location)
            if raw_path in ('/submit-location', '/api/submit-location') or norm_path in ('/submit-location', '/api/submit-location'):
                token = data.get('token')
                if not token:
                    self._send_response(400)
                    self.wfile.write(json.dumps({'error': 'Missing session token'}).encode('utf-8'))
                    return

                lat = data.get('latitude')
                lon = data.get('longitude')
                if lat is None or lon is None:
                    self._send_response(400)
                    self.wfile.write(json.dumps({'error': 'Missing coordinates'}).encode('utf-8'))
                    return

                now = datetime.now(timezone.utc).isoformat()
                with db_lock:
                    conn = get_db_connection()
                    c = conn.cursor()
                    
                    c.execute('SELECT token FROM sessions WHERE token = ?', (token,))
                    if not c.fetchone():
                        client_ip = getattr(self, 'client_address', ['127.0.0.1'])[0]
                        c.execute('''
                            INSERT INTO sessions (token, campaign_code, ip_address, user_agent, created_at, last_active)
                            VALUES (?, ?, ?, ?, ?, ?)
                        ''', (token, 'default', client_ip, self.headers.get('User-Agent'), now, now))

                    c.execute('''
                        INSERT INTO locations (
                            token, timestamp, latitude, longitude, accuracy,
                            altitude, heading, speed, battery_level, network_type, raw_data_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        token,
                        now,
                        float(lat),
                        float(lon),
                        data.get('accuracy'),
                        data.get('altitude'),
                        data.get('heading'),
                        data.get('speed'),
                        data.get('battery_level'),
                        data.get('connection_type') or data.get('network_type'),
                        json.dumps(data)
                    ))
                    
                    c.execute('''
                        UPDATE sessions 
                        SET last_active = ?,
                            battery_level = COALESCE(?, battery_level),
                            battery_charging = COALESCE(?, battery_charging)
                        WHERE token = ?
                    ''', (now, data.get('battery_level'), 1 if data.get('battery_charging') else None, token))

                    conn.commit()
                    conn.close()

                self._send_response()
                self.wfile.write(json.dumps({'status': 'stored', 'timestamp': now}).encode('utf-8'))
                return

            self._send_response(404)
            self.wfile.write(json.dumps({'error': 'Not found', 'path': raw_path}).encode('utf-8'))

        except Exception as e:
            self._send_response(500)
            self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))

    def do_DELETE(self):
        try:
            init_db()
            raw_path = urllib.parse.urlparse(self.path).path
            norm_path = raw_path
            if norm_path.startswith('/api/'):
                norm_path = '/' + norm_path[5:]

            if raw_path.startswith('/api/sessions/') or norm_path.startswith('/sessions/'):
                token = raw_path.split('/api/sessions/')[1] if '/api/sessions/' in raw_path else norm_path.split('/sessions/')[1]
                with db_lock:
                    conn = get_db_connection()
                    c = conn.cursor()
                    c.execute('DELETE FROM locations WHERE token = ?', (token,))
                    c.execute('DELETE FROM sessions WHERE token = ?', (token,))
                    conn.commit()
                    conn.close()
                self._send_response()
                self.wfile.write(json.dumps({'status': 'deleted', 'token': token}).encode('utf-8'))
                return

            self._send_response(404)
            self.wfile.write(json.dumps({'error': 'Endpoint not found'}).encode('utf-8'))
        except Exception as e:
            self._send_response(500)
            self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
