"""MCP stdio bridge. Run through scripts/start.ps1 -Mcp after launching Station."""
import sys
sys.stdin.reconfigure(encoding='utf-8')
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import json
import urllib.request
from core import LOCAL

SCHEMA={'type':'object','additionalProperties':True}
def schema(properties, required=()):
    return {'type':'object','properties':properties,'required':list(required),'additionalProperties':False}

TEXT={'type':'string'}
SCHEMAS={
 'save_project':schema({'id':TEXT,'name':TEXT,'shots':{'type':'array','items':SCHEMA},'idea':TEXT,'draft':SCHEMA,'defaults':SCHEMA},('name','shots')),
 'generate_video':schema({'project':TEXT,'shot':{'type':'object','required':['prompt'],'properties':{
     'id':TEXT,'title':TEXT,'prompt':TEXT,'negative':TEXT,'profile':{'enum':['wan13','wan5']},
     'width':{'type':'integer','minimum':256,'maximum':832,'multipleOf':32},
     'height':{'type':'integer','minimum':256,'maximum':832,'multipleOf':32},
     'frames':{'type':'integer','minimum':9,'maximum':81,'description':'4n+1: 9, 17, 33, 49, 81'},
     'fps':{'type':'integer','minimum':8,'maximum':30},'steps':{'type':'integer','minimum':1,'maximum':50},
     'seed':{'type':'integer','minimum':0},'cfg':{'type':'number','minimum':1,'maximum':12},
     'positive':{'type':'array','items':schema({'label':TEXT,'text':TEXT,'weight':{'type':'number','minimum':0,'maximum':2}},('text',))},
     'negative_tags':{'type':'array','items':SCHEMA},'loras':{'type':'array','items':schema({'file':TEXT,'weight':{'type':'number','minimum':-2,'maximum':2}},('file',))},'image':TEXT
 }}},('shot',)),
 'cancel_job':schema({'id':TEXT},('id',)),
 'prepare_model':schema({'profile':{'enum':['wan13','wan5']}},('profile',)),
 'upload_reference':schema({'name':TEXT,'content':{'type':'string','description':'Base64 PNG/JPEG/WebP bytes, max 50MB'}},('name','content')),
 'export_film':schema({'jobs':{'type':'array','items':TEXT,'minItems':1}},('jobs',))
}
TOOLS=[
 ('station_status','查看模型准备、存储路径和当前任务','GET','/api/status'),
 ('list_projects','列出作品及分镜卡片','GET','/api/projects'),
 ('save_project','保存作品，参数含id、name、shots数组；保留未修改字段','POST','/api/projects'),
 ('keyword_library','获取中英提示词库与解释','GET','/api/keywords'),
 ('generate_video','生成本地视频。参数project以及shot：prompt, profile(wan13/wan5), width, height, frames(4n+1), fps, steps, seed, positive/negative_tags, loras, image(已上传文件名)。返回任务ID','POST','/api/jobs'),
 ('list_jobs','查看进度、错误及output相对路径','GET','/api/jobs'),
 ('cancel_job','取消任务，参数id','POST','/api/cancel'),
 ('prepare_model','准备模型，参数profile: wan13或wan5；可能下载数GB','POST','/api/setup'),
 ('upload_reference','上传参考图片，参数name和content(base64)','POST','/api/upload'),
 ('export_film','按jobs任务ID数组的顺序拼接已完成镜头，输出MP4','POST','/api/export')]

def respond(msg): print(json.dumps(msg,ensure_ascii=False),flush=True)

for line in sys.stdin:
    req={}
    try:
        req=json.loads(line); method=req.get('method'); id=req.get('id')
        if id is None: continue
        if method=='initialize':
            result={'protocolVersion':req.get('params',{}).get('protocolVersion','2024-11-05'),'capabilities':{'tools':{}},'serverInfo':{'name':'eddies-video-station','version':'0.1.0'}}
        elif method=='ping': result={}
        elif method=='tools/list': result={'tools':[{'name':t[0],'description':t[1],'inputSchema':SCHEMAS.get(t[0],schema({}))} for t in TOOLS]}
        elif method=='tools/call':
            params=req['params']; t=next(t for t in TOOLS if t[0]==params['name'])
            data=json.dumps(params.get('arguments',{})).encode() if t[2]=='POST' else None
            token=(LOCAL/'api-token').read_text('ascii')
            call=urllib.request.Request('http://127.0.0.1:8765'+t[3],data=data,headers={'Content-Type':'application/json','X-Station-Token':token})
            try:
                with urllib.request.urlopen(call,timeout=1800) as r: value=r.read().decode()
                result={'content':[{'type':'text','text':value}]}
            except Exception as exc: result={'isError':True,'content':[{'type':'text','text':str(exc)+'；请确认工作站已启动。'}]}
        else:
            respond({'jsonrpc':'2.0','id':id,'error':{'code':-32601,'message':'Method not found'}}); continue
        respond({'jsonrpc':'2.0','id':id,'result':result})
    except Exception as exc:
        respond({'jsonrpc':'2.0','id':req.get('id'),'error':{'code':-32603,'message':str(exc)}})
