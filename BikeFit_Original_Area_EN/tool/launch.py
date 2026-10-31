"""Launch the bundled local server and display its browser address."""
from pathlib import Path
import json
import re
import subprocess
import sys
import time
import urllib.request
import webbrowser

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
READY=HERE/'ready.json'
APP='bikefit_original_area_en_v1'
OPENER=urllib.request.build_opener(urllib.request.ProxyHandler({}))

def running():
    try:
        state=json.loads(READY.read_text(encoding='utf-8'))
        url=state['url']
        if not re.fullmatch(r'http://127\.0\.0\.1:[0-9]{1,5}',url):
            return None
        health=json.loads(OPENER.open(url+'/health',timeout=1).read())
        if health.get('app')==APP and health.get('engine')=='original_closed_white_area_v1':return url
    except (OSError,ValueError,KeyError):
        pass
    return None

def main():
    url=running()
    if url is None:
        with (HERE/'server.log').open('ab') as log:
            process=subprocess.Popen([sys.executable,str(HERE/'server.py'),'--port','0','--ready',str(READY)],
                cwd=ROOT,stdout=log,stderr=log,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError('The local server could not start. See tool/server.log.')
            url=running()
            if url:break
            time.sleep(.15)
        if not url:raise RuntimeError('Startup timed out. See tool/server.log.')
    print('\nBikeFit - Live Video Gap Areas\n')
    print('Local browser address:\n')
    print('    '+url+'\n')
    print('If the browser does not open, copy the address above into Chrome or Edge.')
    print('Then choose your camera, click Turn on camera, and allow camera access.')
    print('Keep the extracted package on this computer while using the tool.\n')
    if '--no-open' not in sys.argv:
        try:
            webbrowser.open(url)
        except OSError:
            print('Please open the address manually.')

if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        print('Startup error: '+str(exc),file=sys.stderr)
        sys.exit(1)
