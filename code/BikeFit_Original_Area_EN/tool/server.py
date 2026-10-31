"""Loopback video inference: line-closed silhouette gap areas, top five."""
from __future__ import annotations
import argparse
import base64
import json
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import cv2
import numpy as np
from semantic_evidence import BicycleSegmenter
from colour_gap_top5 import analyze_colour

APP = 'bikefit_original_area_en_v1'
ENGINE_VERSION = 'original_closed_white_area_v1'


def process_frame(image, detector):
    result = analyze_colour(image, detector)
    ok, encoded = cv2.imencode('.png', result['overlay'])
    if not ok:
        raise ValueError('Could not render the result.')
    return dict(ranking=result['ranking'], instances=result['instances'],
        silhouette_components=result['component_count'], leg_tips=len(result['boundaries']['legs']),
        all_area_count=len(result['regions']), displayed_limit=5,
        ranking_metric=result['ranking_metric'], numbering='rank',
        candidates=len(result['ranked']), width=image.shape[1], height=image.shape[0],
        overlay_base64=base64.b64encode(encoded).decode('ascii'),
        elapsed_ms=result['elapsed_ms'], physical_fit_verified=False, physical_area_calibrated=False)


def analyze(payload, detector):
    try:
        data = base64.b64decode(payload.get('frame_base64',''), validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError('Could not read the video frame.') from exc
    if not data or len(data) > 3*1024*1024:
        raise ValueError('The video frame is invalid or too large. Reconnect the camera.')
    image = cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_COLOR)
    if image is None or max(image.shape[:2]) > 1920:
        raise ValueError('The video frame is invalid or its resolution is too high.')
    return process_frame(image,detector)


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):
        pass

    def send(self,status,data,kind='application/json; charset=utf-8'):
        if isinstance(data,(dict,list)):
            data = json.dumps(data,ensure_ascii=False).encode('utf-8')
        elif isinstance(data,str):
            data = data.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type',kind)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):
            pass

    def do_GET(self):
        route = urlsplit(self.path).path
        if route == '/health':
            return self.send(200,dict(ok=True,app=APP,engine=ENGINE_VERSION))
        if route == '/':
            page = (HERE/'app.html').read_text(encoding='utf-8').replace('__SESSION_TOKEN__',self.server.token)
            return self.send(200,page,'text/html; charset=utf-8')
        if route == '/camera.js':
            return self.send(200,(HERE/'camera.js').read_bytes(),'text/javascript; charset=utf-8')
        return self.send(404,dict(error='Address not found.'))

    def do_POST(self):
        if self.path != '/api/frame':
            return self.send(404,dict(error='Address not found.'))
        if self.headers.get('X-Session-Token') != self.server.token:
            return self.send(403,dict(error='Please refresh the page and try again.'))
        if not self.server.lock.acquire(blocking=False):
            return self.send(409,dict(error='Finishing the previous frame. Detection will resume automatically.'))
        try:
            length = int(self.headers.get('Content-Length','0'))
            if not 0 < length <= 5*1024*1024:
                return self.send(413,dict(error='The video frame is too large.'))
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload,dict):
                raise ValueError('Invalid video frame data.')
            if self.server.detector is None:
                self.server.detector = BicycleSegmenter(ROOT/'models/yolov8s-seg.onnx')
            self.send(200,analyze(payload,self.server.detector))
        except (ValueError, KeyError, TypeError, cv2.error) as exc:
            self.send(400,dict(error=str(exc)))
        except Exception:
            import traceback
            traceback.print_exc()
            self.send(500,dict(error='Detection failed. Retrying automatically.'))
        finally:
            self.server.lock.release()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=0)
    parser.add_argument('--ready',type=Path,default=HERE/'ready.json')
    args = parser.parse_args()
    cv2.setNumThreads(4)
    server = ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    server.token = secrets.token_urlsafe(24)
    server.lock = threading.Lock()
    server.detector = None
    url = f'http://127.0.0.1:{server.server_port}'
    args.ready.write_text(json.dumps(dict(url=url,app=APP)),encoding='utf-8')
    print(url,flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
