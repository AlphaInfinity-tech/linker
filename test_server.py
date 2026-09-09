import urllib.request
import urllib.parse
import json
import time
import subprocess
import sys
import os

BASE_URL = 'http://localhost:8000'

def test_suite():
    print(">>> Starting GEOTRACE / Linker Comprehensive Test Suite...")
    test_token = f"test-sess-{int(time.time())}"

    # 1. Test GET / (Client Tracker UI)
    print("\n[1/7] Testing GET / (Client Tracker HTML)...")
    req = urllib.request.urlopen(f"{BASE_URL}/")
    html = req.read().decode('utf-8')
    assert req.status == 200, f"Expected 200, got {req.status}"
    assert 'GEOTRACE' in html, "Missing GEOTRACE brand in HTML"
    assert 'watchPosition' in html, "Missing watchPosition in HTML"
    print("  [PASS] GET / passed successfully.")

    # 2. Test GET /admin (Admin Dashboard UI)
    print("\n[2/7] Testing GET /admin (Admin Console HTML)...")
    req = urllib.request.urlopen(f"{BASE_URL}/admin")
    admin_html = req.read().decode('utf-8')
    assert req.status == 200, f"Expected 200, got {req.status}"
    assert 'COMMAND CONSOLE' in admin_html, "Missing Command Console brand in HTML"
    assert 'playbackSlider' in admin_html, "Missing playback slider in HTML"
    print("  [PASS] GET /admin passed successfully.")

    # 3. Test POST /consent (Register Session with Enhanced Fingerprint)
    print("\n[3/7] Testing POST /consent (Device Fingerprinting & Handshake)...")
    consent_payload = {
        "consent": True,
        "token": test_token,
        "campaign_code": "weather",
        "browser": "Chrome 128",
        "os": "Windows 11",
        "device_type": "Desktop",
        "screen_res": "2560x1440",
        "viewport": "1920x1080",
        "pixel_ratio": 1.25,
        "language": "en-US",
        "timezone": "America/New_York",
        "cpu_cores": 16,
        "gpu_vendor": "NVIDIA",
        "gpu_renderer": "NVIDIA GeForce RTX 4080 Direct3D11",
        "battery_level": 88,
        "battery_charging": False,
        "connection_type": "4g",
        "connection_downlink": 120.5
    }
    data = json.dumps(consent_payload).encode('utf-8')
    req = urllib.request.Request(f"{BASE_URL}/consent", data=data, headers={'Content-Type': 'application/json'})
    resp = urllib.request.urlopen(req)
    res_data = json.loads(resp.read().decode('utf-8'))
    assert res_data.get('status') == 'consent_recorded'
    assert res_data.get('token') == test_token
    print(f"  [PASS] Session Registered with Token: {res_data.get('token')}")

    # 4. Test POST /submit-location (Stream 4 GPS fixes simulating movement)
    print("\n[4/7] Testing POST /submit-location (Streaming Multi-Point GPS Trail)...")
    test_points = [
        {"latitude": 40.712776, "longitude": -74.005974, "accuracy": 5.0, "speed": 1.2, "altitude": 10.0, "heading": 90.0},
        {"latitude": 40.713500, "longitude": -74.004800, "accuracy": 4.5, "speed": 2.5, "altitude": 11.2, "heading": 95.0},
        {"latitude": 40.714200, "longitude": -74.003500, "accuracy": 4.0, "speed": 3.1, "altitude": 12.0, "heading": 100.0},
        {"latitude": 40.715000, "longitude": -74.002000, "accuracy": 3.5, "speed": 4.0, "altitude": 12.8, "heading": 105.0}
    ]
    for i, pt in enumerate(test_points):
        pt_payload = {
            "token": test_token,
            "latitude": pt["latitude"],
            "longitude": pt["longitude"],
            "accuracy": pt["accuracy"],
            "altitude": pt["altitude"],
            "heading": pt["heading"],
            "speed": pt["speed"],
            "battery_level": 87 - i,
            "battery_charging": False,
            "connection_type": "4g"
        }
        req = urllib.request.Request(f"{BASE_URL}/submit-location", data=json.dumps(pt_payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
        resp = urllib.request.urlopen(req)
        res_data = json.loads(resp.read().decode('utf-8'))
        assert res_data.get('status') == 'stored'
        print(f"  [PASS] Stored GPS Fix #{i+1}: Lat={pt['latitude']}, Lon={pt['longitude']}, Speed={pt['speed']} m/s")

    # 5. Test GET /api/sessions and /api/sessions/<token>
    print("\n[5/7] Testing GET /api/sessions & Distance Metrics...")
    req = urllib.request.urlopen(f"{BASE_URL}/api/sessions")
    sessions = json.loads(req.read().decode('utf-8'))
    found = [s for s in sessions if s['token'] == test_token]
    assert len(found) == 1, "Session not returned in /api/sessions"
    sess = found[0]
    print(f"  Session Metrics: Location Count = {sess['location_count']}, Total Distance = {sess['total_distance_m']} meters ({sess['total_distance_km']} km)")
    assert sess['location_count'] == 4, f"Expected 4 locations, got {sess['location_count']}"
    assert sess['total_distance_m'] > 100, f"Expected distance > 100m, got {sess['total_distance_m']}"

    # Detailed session check
    req = urllib.request.urlopen(f"{BASE_URL}/api/sessions/{test_token}")
    sess_detail = json.loads(req.read().decode('utf-8'))
    assert len(sess_detail['locations']) == 4
    assert sess_detail['gpu_vendor'] == 'NVIDIA'
    print("  [PASS] Session detailed trail query passed.")

    # 6. Test Campaign Management POST /api/campaigns and GET /api/campaigns
    print("\n[6/7] Testing Campaign Link Management...")
    camp_payload = {
        "code": f"speedtest_ny_{int(time.time())}",
        "name": "New York 5G Speed Test Survey",
        "template": "speedtest"
    }
    req = urllib.request.Request(f"{BASE_URL}/api/campaigns", data=json.dumps(camp_payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
    resp = urllib.request.urlopen(req)
    assert resp.status == 201
    print("  [PASS] Created new campaign")

    req = urllib.request.urlopen(f"{BASE_URL}/api/campaigns")
    camps = json.loads(req.read().decode('utf-8'))
    camp_codes = [c['code'] for c in camps]
    assert camp_payload['code'] in camp_codes
    print(f"  [PASS] Campaigns list verified.")

    # 7. Test Export Endpoints (GeoJSON, CSV, JSON)
    print("\n[7/7] Testing Data Export Formats (GeoJSON, CSV, JSON)...")
    
    # GeoJSON
    req = urllib.request.urlopen(f"{BASE_URL}/api/export?format=geojson&session={test_token}")
    geojson_data = json.loads(req.read().decode('utf-8'))
    assert geojson_data['type'] == 'FeatureCollection'
    assert len(geojson_data['features']) == 5 # 4 Points + 1 LineString
    print(f"  [PASS] GeoJSON Export: {len(geojson_data['features'])} features (Points & LineString)")

    # CSV
    req = urllib.request.urlopen(f"{BASE_URL}/api/export?format=csv&session={test_token}")
    csv_text = req.read().decode('utf-8')
    csv_lines = [l for l in csv_text.strip().split('\n') if l]
    assert len(csv_lines) == 5 # 1 Header + 4 data rows
    print(f"  [PASS] CSV Export: {len(csv_lines)} rows including header")

    # JSON
    req = urllib.request.urlopen(f"{BASE_URL}/api/export?format=json")
    json_export = json.loads(req.read().decode('utf-8'))
    assert 'sessions' in json_export and 'locations' in json_export
    print(f"  [PASS] JSON Export: {len(json_export['sessions'])} sessions, {len(json_export['locations'])} locations")

    print("\n>>> ALL TESTS PASSED SUCCESSFULLY! GEOTRACE / Linker is fully operational.")

if __name__ == '__main__':
    test_suite()
