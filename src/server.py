"""Loopback-only API and static UI; no system Python packages required."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
import secrets
import subprocess
import threading
import urllib.parse
import uuid
from core import Station, ROOT, LOCAL

LEXICON = json.loads((ROOT/'configs/keywords.json').read_text('utf-8'))

def browse_folder():
    cmd="Add-Type -AssemblyName System.Windows.Forms; $d=New-Object System.Windows.Forms.FolderBrowserDialog; $d.Description='Choose Video Station storage folder'; if($d.ShowDialog() -eq 'OK'){ [Console]::OutputEncoding=[Text.Encoding]::UTF8; Write-Output $d.SelectedPath }"
    result=subprocess.run(['powershell.exe','-NoProfile','-STA','-Command',cmd],capture_output=True,timeout=180)
    return {'path':result.stdout.decode('utf-8-sig').strip()}

class Handler(BaseHTTPRequestHandler):
    server_version='VideoStation/0.1'
    def log_message(self,fmt,*args):
        print(fmt % args,flush=True)

    def valid_host(self):
        return self.headers.get('Host') in ('127.0.0.1:8765','localhost:8765')

    def send_json(self,value,code=200):
        data=json.dumps(value,ensure_ascii=False).encode('utf-8')
        self.send_response(code); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(data))); self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff'); self.end_headers(); self.wfile.write(data)

    def do_GET(self):
        if not self.valid_host(): return self.send_json({'error':'Host rejected'},403)
        p=urllib.parse.urlparse(self.path)
        try:
            if p.path=='/api/health': return self.send_json({'app':'eddies-video-station','version':'0.1.0'})
            if p.path=='/api/session': return self.send_json({'token':TOKEN})
            if p.path=='/api/status': return self.send_json(station.status())
            if p.path=='/api/projects': return self.send_json(station.projects())
            if p.path=='/api/jobs': return self.send_json(station.jobs())
            if p.path=='/api/keywords': return self.send_json(LEXICON)
            if p.path=='/api/logs':
                name=urllib.parse.parse_qs(p.query).get('name',['engine'])[0]
                if name not in ('engine','download','install','export'): raise ValueError('未知日志')
                file=station.data/'logs'/(name+'.log')
                if file.exists():
                    with file.open('rb') as f:
                        f.seek(max(0,file.stat().st_size-32000)); text=f.read().decode('utf-8',errors='replace')
                else: text='还没有日志。'
                return self.send_json({'text':text})
            if p.path.startswith('/media/'):
                rel=urllib.parse.unquote(p.path[len('/media/'):]); path=(station.data/rel).resolve()
                if not any(path.is_relative_to(station.data/d) for d in ('input','output')): raise ValueError('无效的资源路径')
                return self.send_file(path)
            if p.path.startswith('/api/'): return self.send_json({'error':'接口不存在'},404)
            path=(ROOT/'web'/('index.html' if p.path=='/' else urllib.parse.unquote(p.path.lstrip('/')))).resolve()
            if not path.is_relative_to(ROOT/'web'): return self.send_json({'error':'Not found'},404)
            return self.send_file(path)
        except (ValueError,KeyError) as exc: self.send_json({'error':str(exc)},400)
        except Exception as exc: self.send_json({'error':str(exc)},500)

    def send_file(self,path):
        if not path.is_file(): return self.send_json({'error':'文件不存在'},404)
        size=path.stat().st_size; start=0; end=size-1
        range_header=self.headers.get('Range','')
        code=200
        if range_header.startswith('bytes='):
            a,b=range_header[6:].split('-',1)
            if a: start=int(a); end=min(int(b) if b else end,end)
            else: start=max(0,size-int(b))
            if start>end or start<0: return self.send_json({'error':'Invalid range'},416)
            code=206
        self.send_response(code)
        self.send_header('Content-Type',mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
        self.send_header('Content-Length',str(end-start+1)); self.send_header('Accept-Ranges','bytes'); self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self'; script-src 'self'; frame-ancestors 'none'")
        if code==206: self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
        self.end_headers()
        with path.open('rb') as f:
            f.seek(start); remaining=end-start+1
            while remaining:
                block=f.read(min(1024*1024,remaining))
                if not block: break
                try: self.wfile.write(block)
                except (BrokenPipeError,ConnectionResetError): break
                remaining-=len(block)

    def do_POST(self):
        origin=self.headers.get('Origin')
        if not self.valid_host() or self.headers.get('X-Station-Token')!=TOKEN or (origin and origin not in ('http://127.0.0.1:8765','http://localhost:8765')):
            return self.send_json({'error':'请求验证失败，请刷新页面'},403)
        try:
            length=int(self.headers.get('Content-Length','0'))
            if length>70_000_000: raise ValueError('上传文件过大，图片请控制在50MB以内')
            data=json.loads(self.rfile.read(length) or '{}'); path=urllib.parse.urlparse(self.path).path
            if path=='/api/projects': result=station.save_project(data)
            elif path=='/api/settings': result=station.settings(data)
            elif path=='/api/setup': result=station.prepare_async(data.get('profile','wan13'))
            elif path=='/api/jobs': result=station.submit(data)
            elif path=='/api/cancel': result=station.cancel_job(data['id'])
            elif path=='/api/export': result=station.export(data)
            elif path=='/api/browse': result=browse_folder()
            elif path=='/api/upload':
                ext=Path(data['name']).suffix.lower()
                if ext not in ('.png','.jpg','.jpeg','.webp'): raise ValueError('请上传PNG、JPEG或WebP图片')
                content=base64.b64decode(data['content'],validate=True)
                if not content or len(content)>50_000_000: raise ValueError('图片大小不正确')
                good=(content.startswith(b'\x89PNG\r\n\x1a\n') or content.startswith(b'\xff\xd8\xff') or (content[:4]==b'RIFF' and content[8:12]==b'WEBP'))
                if not good: raise ValueError('文件不是支持的图片格式')
                name=uuid.uuid4().hex+ext; (station.data/'input'/name).write_bytes(content)
                result={'name':name,'url':'/media/input/'+name}
            elif path=='/api/open-folder':
                key=data.get('folder','output')
                if key not in ('models','output','input','logs'): raise ValueError('未知文件夹')
                os.startfile(str(station.data/key)); result={'ok':True}
            elif path=='/api/suggest':
                text=str(data.get('text','')).lower()
                # Explicit, deterministic keyword matching. Never invent a subject/style.
                result={'source':'本地词库匹配','tags':[t for t in LEXICON if t['label'].lower() in text or t['text'].lower() in text][:30]}
            elif path=='/api/stop-engine':
                if station.active: raise ValueError('请先取消正在生成的任务')
                if station.process and station.process.poll() is None: station.process.terminate(); station.process.wait(timeout=20)
                station.process=None; result={'ok':True}
            else: return self.send_json({'error':'接口不存在'},404)
            self.send_json(result)
        except (ValueError,KeyError,StopIteration) as exc: self.send_json({'error':str(exc) or '数据不正确'},400)
        except Exception as exc: self.send_json({'error':str(exc)},500)

if __name__=='__main__':
    server=ThreadingHTTPServer(('127.0.0.1',8765),Handler)
    # Bind first: a second launcher must not reset jobs or invalidate the token.
    station=Station()
    TOKEN=secrets.token_urlsafe(32)
    (LOCAL/'api-token').write_text(TOKEN,'ascii')
    threading.Thread(target=station.worker,daemon=True).start()
    print('Video Station http://127.0.0.1:8765',flush=True)
    try: server.serve_forever()
    finally:
        station.stopping=True
        if station.process and station.process.poll() is None: station.process.terminate()
