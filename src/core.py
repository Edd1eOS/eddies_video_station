"""Portable local workspace, verified provisioning and sequential video jobs."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import threading
import time
import urllib.request
import urllib.error
import urllib.parse
import uuid
import re
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / '.local'
LOCAL.mkdir(exist_ok=True)
MANIFEST = json.loads((ROOT / 'configs/models.json').read_text('utf-8'))
FLAGS = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

def request(url, data=None, timeout=30):
    req = urllib.request.Request(url, data=None if data is None else json.dumps(data).encode(), headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return json.load(res)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'生成引擎拒绝请求：{exc.read().decode()[:3000]}') from exc

def digest(path):
    with open(path, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def bounded(value, low, high, name, integer=True):
    n = int(value) if integer else float(value)
    if not low <= n <= high:
        raise ValueError(f'{name}应在 {low}–{high} 之间')
    return n

def validate_shot(shot):
    s = dict(shot)
    s['profile'] = s.get('profile', 'wan13')
    if s['profile'] not in ('wan13','wan5'): raise ValueError('请选择已支持的模型')
    if not str(s.get('prompt','')).strip(): raise ValueError('先写下这个镜头的内容')
    s['width'] = bounded(s.get('width',512),256,832,'宽度')
    s['height'] = bounded(s.get('height',320),256,832,'高度')
    if s['width'] % 32 or s['height'] % 32: raise ValueError('宽高必须是32的倍数')
    s['frames'] = bounded(s.get('frames',33),9,81,'帧数')
    if s['frames'] % 4 != 1: raise ValueError('帧数应为 4n+1，例如33、49、81')
    s['fps'] = bounded(s.get('fps',16),8,30,'帧率')
    s['steps'] = bounded(s.get('steps',20),1,50,'采样步数')
    s['cfg'] = bounded(s.get('cfg',5),1,12,'提示强度',False)
    s['seed'] = bounded(s.get('seed',42),0,2**53-1,'随机种子')
    if s.get('image') and s['profile'] != 'wan5': raise ValueError('首帧参考需要选择 Wan 2.2')
    for field in ('positive','negative_tags'):
        for tag in s.get(field,[]):
            bounded(tag.get('weight',1),0,2,'词条强度',False)
    for lora in s.get('loras',[]):
        if Path(lora['file']).name != lora['file'] or not lora['file'].endswith('.safetensors'): raise ValueError('LoRA文件名无效')
        bounded(lora.get('weight',1),-2,2,'LoRA强度',False)
    return s

def prompt_text(text, tags):
    # Wan receives natural language. Tag weights prioritize clauses, not SD syntax.
    parts = [str(text).strip()]
    for t in sorted(tags, key=lambda t:float(t.get('weight',1)), reverse=True):
        w = float(t.get('weight',1))
        if w <= 0: continue
        term = str(t.get('text','')).strip()
        if term: parts.append(('Emphasize: ' if w > 1.25 else '') + term)
    return '. '.join(p for p in parts if p)

def workflow(shot, prefix):
    s = validate_shot(shot)
    five = s['profile'] == 'wan5'
    files = MANIFEST['files']
    filename = lambda key:Path(files[key]['path']).name
    g = {
      '1':{'class_type':'UNETLoader','inputs':{'unet_name':filename('wan5' if five else 'wan13'),'weight_dtype':'default'}},
      '2':{'class_type':'CLIPLoader','inputs':{'clip_name':filename('text'),'type':'wan','device':'cpu'}},
      '3':{'class_type':'VAELoader','inputs':{'vae_name':filename('vae22' if five else 'vae21')}},
      '4':{'class_type':'CLIPTextEncode','inputs':{'clip':['2',0],'text':prompt_text(s['prompt'],s.get('positive',[]))}},
      '5':{'class_type':'CLIPTextEncode','inputs':{'clip':['2',0],'text':prompt_text(s.get('negative',''),s.get('negative_tags',[]))}},
      '6':{'class_type':'Wan22ImageToVideoLatent' if five else 'EmptyHunyuanLatentVideo','inputs':{'width':s['width'],'height':s['height'],'length':s['frames'],'batch_size':1}},
      '7':{'class_type':'ModelSamplingSD3','inputs':{'model':['1',0],'shift':8.0}},
      '8':{'class_type':'KSampler','inputs':{'model':['7',0],'positive':['4',0],'negative':['5',0],'latent_image':['6',0],'seed':s['seed'],'steps':s['steps'],'cfg':s['cfg'],'sampler_name':'uni_pc','scheduler':'simple','denoise':1}},
      '9':{'class_type':'VAEDecodeTiled','inputs':{'samples':['8',0],'vae':['3',0],'tile_size':256,'overlap':64,'temporal_size':16,'temporal_overlap':4}},
      '10':{'class_type':'CreateVideo','inputs':{'images':['9',0],'fps':s['fps']}},
      '11':{'class_type':'SaveVideo','inputs':{'video':['10',0],'filename_prefix':prefix,'format':'auto','codec':'auto'}}
    }
    if five: g['6']['inputs']['vae'] = ['3',0]
    if s.get('image'):
        g['12'] = {'class_type':'LoadImage','inputs':{'image':s['image']}}
        g['6']['inputs']['start_image'] = ['12',0]
    model = ['1',0]
    for i,lora in enumerate(s.get('loras',[])):
        key = str(20+i)
        g[key] = {'class_type':'LoraLoaderModelOnly','inputs':{'model':model,'lora_name':lora['file'],'strength_model':float(lora.get('weight',1))}}
        model = [key,0]
    g['7']['inputs']['model'] = model
    return g

class Station:
    def __init__(self, root=None):
        self.config_path = LOCAL / 'settings.json'
        self.config = json.loads(self.config_path.read_text('utf-8')) if self.config_path.exists() else {}
        self.data = Path(root or self.config.get('data_root',ROOT / 'data')).resolve()
        self.busy = threading.Lock()
        self.provision = {'state':'idle','message':'首次生成时自动准备所需组件','progress':0}
        self.process = None
        self.cancel = set()
        self.active = None
        self.stopping = False
        self.layout()
        self.sql("UPDATE jobs SET state='failed',error='工作站重启，任务未完成；可重新生成。' WHERE state IN ('running','queued')")

    def layout(self):
        for d in ('models','input','output','downloads','logs','projects','temp','user'):
            (self.data/d).mkdir(parents=True,exist_ok=True)
        for d in ('diffusion_models','text_encoders','vae','loras','checkpoints'):
            (self.data/'models'/d).mkdir(exist_ok=True)
        with self.connect() as db:
            db.executescript('CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,body TEXT NOT NULL,updated REAL); CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,project TEXT,shot TEXT,body TEXT,state TEXT,progress REAL DEFAULT 0,error TEXT DEFAULT "",output TEXT DEFAULT "",created REAL);')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.data/'station.db',timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db: yield db
        finally: db.close()

    def sql(self,q,args=()):
        with self.connect() as db:
            return [dict(r) for r in db.execute(q,args).fetchall()]

    def settings(self, data):
        if Path(data.get('data_root',self.data)).resolve()==self.data: return self.status()
        if self.active or self.busy.locked() or self.sql("SELECT id FROM jobs WHERE state='queued' LIMIT 1"): raise ValueError('请等当前任务结束后再修改位置')
        path = Path(data.get('data_root',self.data)).expanduser()
        if not path.is_absolute(): raise ValueError('请选择绝对路径')
        self.data = path.resolve()
        self.layout()
        self.config['data_root'] = str(self.data)
        # Changing workspace opens its own database; existing work is never moved/deleted.
        self.config_path.write_text(json.dumps(self.config,ensure_ascii=False,indent=2),'utf-8')
        if self.process: self.process.terminate(); self.process.wait(timeout=20); self.process=None
        return self.status()

    def profile(self, id):
        return next(p for p in MANIFEST['profiles'] if p['id']==id)

    def runtime(self):
        base = Path(self.config.get('engine_root',ROOT/'.runtime'/'engine'))
        marker=base/'.ready'
        if not marker.exists() or marker.read_text('ascii').strip()!=MANIFEST['engine']['sha256']: return None
        for python in base.glob('**/python_embed*/python.exe'):
            main = python.parent.parent/'ComfyUI'/'main.py'
            if main.exists(): return python,main
        return None

    def status(self):
        profiles = []
        for p in MANIFEST['profiles']:
            missing = [MANIFEST['files'][k] for k in p['files'] if not self.file_ready(MANIFEST['files'][k])]
            profiles.append({**p,'ready':not missing,'download_bytes':sum(f['size'] for f in missing)})
        return {'repository_root':str(ROOT),'data_root':str(self.data),'engine_installed':bool(self.runtime()),'provision':dict(self.provision),'profiles':profiles,'active':self.active,'free_bytes':shutil.disk_usage(self.data).free,'loras':[p.name for p in (self.data/'models/loras').glob('*.safetensors')], 'engine':'ComfyUI 0.37.0 · 独立进程', 'assistant':'词库匹配（本地，无语言模型）'}

    def file_ready(self,f):
        p=self.data/'models'/f['path']
        marker=p.with_suffix('.verified')
        try:
            return p.exists() and p.stat().st_size==f['size'] and marker.exists() and marker.stat().st_mtime>=p.stat().st_mtime and marker.read_text('ascii')==f['sha256']
        except (OSError,UnicodeError): return False

    def download(self, url, target, sha, size):
        target=Path(target); target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists() and target.stat().st_size==size and digest(target)==sha: return
        part=Path(str(target)+'.part')
        if part.exists() and part.stat().st_size>size: part.unlink()
        self.provision.update(message='下载 '+target.name,progress=0)
        if not part.exists() or part.stat().st_size<size:
            with open(self.data/'logs/download.log','ab') as log:
                log_start=log.tell()
                initial=part.stat().st_size if part.exists() else 0
                p=subprocess.Popen(['curl.exe','--fail','--location','--retry','5','--retry-delay','3','--connect-timeout','30','--speed-time','90','--speed-limit','1024','--continue-at','-','--output',str(part),url],stdout=log,stderr=log,creationflags=FLAGS)
                while p.poll() is None:
                    downloaded=part.stat().st_size if part.exists() else 0
                    # Windows may not publish file length while curl still has it open.
                    with open(self.data/'logs/download.log','rb') as progress_log:
                        progress_log.seek(max(log_start,progress_log.seek(0,2)-4096))
                        percentages=re.findall(rb'(?:^|[\r\n])\s*(\d{1,3})\s+[\d.]',progress_log.read())
                    if percentages: downloaded=max(downloaded,initial+(size-initial)*min(100,int(percentages[-1]))/100)
                    self.provision['progress']=round(100*downloaded/size,1)
                    time.sleep(.5)
                if p.returncode: raise RuntimeError('下载中断，已保留进度。点击准备模型可继续；详情见下载日志。')
        self.provision['message']='校验 '+target.name
        if part.stat().st_size!=size or digest(part)!=sha:
            part.rename(part.with_name(part.name+'.invalid-'+uuid.uuid4().hex[:6]))
            raise RuntimeError('下载文件校验失败；再次准备将重新下载。')
        part.replace(target)

    def prepare(self,profile):
        with self.busy:
            self.provision.update(state='running',message='检查本地组件',progress=0)
            try:
                if not self.runtime():
                    e=MANIFEST['engine']; archive=self.data/'downloads/engine.7z'
                    if shutil.disk_usage(ROOT).free < 7*1024**3: raise RuntimeError('启动器所在磁盘需要至少7GB可用空间来准备运行环境')
                    self.download(e['url'],archive,e['sha256'],e['size'])
                    self.provision['message']='解压独立生成环境'
                    target=ROOT/'.runtime/engine'; target.mkdir(parents=True,exist_ok=True)
                    with open(self.data/'logs/install.log','ab') as log:
                        subprocess.run(['tar.exe','-xf',str(archive),'-C',str(target)],stdout=log,stderr=log,check=True,creationflags=FLAGS)
                    (target/'.ready').write_text(e['sha256'],'ascii')
                    if not self.runtime(): raise RuntimeError('环境解压未完成，查看安装日志后重试')
                for k in self.profile(profile)['files']:
                    f=MANIFEST['files'][k]
                    if self.file_ready(f): continue
                    target=self.data/'models'/f['path']
                    if shutil.disk_usage(self.data).free < f['size']+2*1024**3: raise RuntimeError('磁盘空间不足，请选择空间更大的存储目录')
                    self.download(f"https://huggingface.co/{f['repo']}/resolve/{f['revision']}/split_files/{f['path']}",target,f['sha256'],f['size'])
                    target.with_suffix('.verified').write_text(f['sha256'],'ascii')
                self.provision.update(state='ready',message='环境和模型已准备好',progress=100)
            except Exception as exc:
                self.provision.update(state='failed',message=str(exc))
                raise

    def prepare_async(self,profile):
        self.profile(profile)
        if self.busy.locked() or self.provision['state']=='running': return self.status()
        self.provision['state']='running'
        def work():
            try: self.prepare(profile)
            except Exception: pass
        threading.Thread(target=work,daemon=True).start()
        return self.status()

    @property
    def engine_url(self): return 'http://127.0.0.1:8191'

    def start_engine(self):
        if self.process and self.process.poll() is None:
            try: request(self.engine_url+'/system_stats',timeout=2); return
            except Exception: pass
        else:
            # Never attach to or terminate an unrelated engine occupying our port.
            import socket
            with socket.socket() as sock:
                if sock.connect_ex(('127.0.0.1',8191))==0: raise RuntimeError('端口8191被其他程序占用，请关闭该程序后重试')
            py,main=self.runtime()
            log=open(self.data/'logs/engine.log','ab')
            cmd=[str(py),'-s',str(main),'--windows-standalone-build','--listen','127.0.0.1','--port','8191','--disable-auto-launch','--disable-api-nodes','--disable-all-custom-nodes','--lowvram','--preview-method','none','--base-directory',str(self.data),'--input-directory',str(self.data/'input'),'--output-directory',str(self.data/'output'),'--user-directory',str(self.data/'user'),'--temp-directory',str(self.data/'temp')]
            self.process=subprocess.Popen(cmd,cwd=main.parent,stdout=log,stderr=log,creationflags=FLAGS); log.close()
        for _ in range(180):
            if self.process.poll() is not None: raise RuntimeError('生成引擎启动失败，请打开引擎日志查看具体原因')
            try: request(self.engine_url+'/system_stats',timeout=2); return
            except Exception: time.sleep(1)
        raise RuntimeError('引擎启动超时，请查看引擎日志')

    def projects(self):
        return [json.loads(r['body']) for r in self.sql('SELECT body FROM projects ORDER BY updated DESC')]

    def save_project(self,p):
        p=dict(p); p.setdefault('id',uuid.uuid4().hex); p.setdefault('name','未命名作品'); p.setdefault('shots',[])
        if not isinstance(p['id'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',p['id']): raise ValueError('项目标识无效')
        if not isinstance(p['name'],str) or not isinstance(p['shots'],list): raise ValueError('项目格式无效')
        for s in p['shots']:
            if not isinstance(s.get('id'),str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',s['id']): raise ValueError('镜头标识无效')
            s.update(validate_shot(s))
        if len(json.dumps(p))>2_000_000: raise ValueError('项目太大')
        self.sql('INSERT INTO projects VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body,updated=excluded.updated',(p['id'],json.dumps(p,ensure_ascii=False),time.time()))
        return p

    def submit(self,data):
        s=validate_shot(data['shot']); id=uuid.uuid4().hex
        if s.get('image') and not (self.data/'input'/Path(s['image']).name).exists(): raise ValueError('首帧文件不存在，请重新上传')
        if s.get('image') and Path(s['image']).name!=s['image']: raise ValueError('首帧路径无效')
        for lora in s.get('loras',[]):
            if not (self.data/'models/loras'/lora['file']).exists(): raise ValueError('LoRA文件不存在')
        self.sql('INSERT INTO jobs(id,project,shot,body,state,created) VALUES(?,?,?,?,?,?)',(id,data.get('project',''),s.get('id',''),json.dumps(s,ensure_ascii=False),'queued',time.time()))
        return {'id':id,'state':'queued'}

    def jobs(self): return self.sql('SELECT * FROM jobs ORDER BY created DESC LIMIT 200')

    def cancel_job(self,id):
        self.cancel.add(id)
        self.sql("UPDATE jobs SET state='cancelled' WHERE id=? AND state='queued'",(id,))
        if self.active==id and self.process:
            request(self.engine_url+'/interrupt',{})
        return {'ok':True}

    def worker(self):
        while not self.stopping:
            rows=self.sql("SELECT * FROM jobs WHERE state='queued' ORDER BY created LIMIT 1")
            if not rows: time.sleep(.5); continue
            job=rows[0]; id=job['id']; self.active=id
            try:
                self.sql("UPDATE jobs SET state='running',progress=1 WHERE id=?",(id,))
                s=json.loads(job['body']); self.prepare(s['profile'])
                if id in self.cancel: raise InterruptedError('已取消')
                self.start_engine()
                graph=workflow(s,'station/'+id)
                response=request(self.engine_url+'/prompt',{'prompt':graph,'client_id':'video-station'})
                pid=response['prompt_id']; start=time.time()
                while True:
                    if id in self.cancel:
                        request(self.engine_url+'/queue',{'delete':[pid]})
                        request(self.engine_url+'/interrupt',{})
                        raise InterruptedError('已取消')
                    history=request(self.engine_url+'/history/'+pid)
                    if pid in history:
                        entry=history[pid]
                        if entry.get('status',{}).get('status_str')=='error':
                            raise RuntimeError(json.dumps(entry['status'].get('messages',[]),ensure_ascii=False)[-2500:])
                        outputs=list((self.data/'output/station').glob(id+'*.mp4'))
                        if not outputs: raise RuntimeError('引擎已返回，但没有生成MP4；请查看引擎日志')
                        file=outputs[0]
                        file.with_suffix('.json').write_text(json.dumps({'shot':s,'graph':graph,'engine':MANIFEST['engine']['version'],'created':time.time()},ensure_ascii=False,indent=2),'utf-8')
                        self.sql("UPDATE jobs SET state='done',progress=100,output=? WHERE id=?",(file.relative_to(self.data/'output').as_posix(),id))
                        break
                    if time.time()-start>21600: raise RuntimeError('任务超过6小时，请查看引擎日志')
                    time.sleep(2)
            except InterruptedError:
                self.sql("UPDATE jobs SET state='cancelled',error='用户取消' WHERE id=?",(id,))
            except Exception as exc:
                self.sql("UPDATE jobs SET state='failed',error=? WHERE id=?",(str(exc),id))
            finally: self.active=None

    def export(self,data):
        ids=data.get('jobs',[])
        if not ids: raise ValueError('请先选择已完成的镜头')
        files=[]
        for id in ids:
            rows=self.sql("SELECT output FROM jobs WHERE id=? AND state='done'",(id,))
            if not rows: raise ValueError('只可合并已完成的镜头')
            files.append(self.data/'output'/rows[0]['output'])
        runtime=self.runtime()
        if not runtime: raise ValueError('请先准备生成环境')
        name='film-'+uuid.uuid4().hex[:12]+'.mp4'; out=self.data/'output'/name
        # Re-encode each stream at common dimensions/fps to avoid broken mixed clips.
        cmd=[str(runtime[0]),'-s',str(ROOT/'src/export_video.py')]
        with open(self.data/'logs/export.log','ab') as log:
            subprocess.run(cmd,input=json.dumps({'files':[str(f) for f in files],'output':str(out)}).encode(),stdout=log,stderr=log,check=True,timeout=1800,creationflags=FLAGS)
        return {'output':name}
