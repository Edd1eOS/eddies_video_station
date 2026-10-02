import base64
import http.client
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import server
from core import Station


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        server.station=Station(cls.tmp.name)
        server.TOKEN='unit-test-only'
        cls.http=ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown(); cls.http.server_close(); cls.thread.join(); cls.tmp.cleanup()

    def call(self,path,body=None,headers=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.http.server_port)
        hdr={'Host':'127.0.0.1:8765','Content-Type':'application/json','X-Station-Token':server.TOKEN,**(headers or {})}
        conn.request('GET' if body is None else 'POST',path,body=None if body is None else json.dumps(body),headers=hdr)
        res=conn.getresponse(); status=res.status; data=res.read(); conn.close()
        return status,data

    def test_origin_host_and_token(self):
        self.assertEqual(self.call('/api/projects',{}, {'X-Station-Token':'bad'})[0],403)
        self.assertEqual(self.call('/api/projects',{}, {'Origin':'https://evil.example'})[0],403)
        self.assertEqual(self.call('/api/status',headers={'Host':'evil.example'})[0],403)

    def test_health_project_and_bad_job(self):
        self.assertEqual(json.loads(self.call('/api/health')[1])['app'],'eddies-video-station')
        status,body=self.call('/api/projects',{'name':'测试','shots':[]})
        self.assertEqual(status,200)
        self.assertEqual(json.loads(body)['name'],'测试')
        self.assertEqual(self.call('/api/jobs',{'shot':{'prompt':''}})[0],400)

    def test_paths_and_ranges(self):
        self.assertEqual(self.call('/media/../station.db')[0],400)
        self.assertEqual(self.call('/../src/core.py')[0],404)
        (server.station.data/'output/test.mp4').write_bytes(b'0123456789')
        status,body=self.call('/media/output/test.mp4',headers={'Range':'bytes=2-5'})
        self.assertEqual((status,body),(206,b'2345'))
        self.assertEqual(self.call('/media/output/test.mp4',headers={'Range':'bytes=100-'})[0],416)

    def test_upload_rejects_disguised_code(self):
        self.assertEqual(self.call('/api/upload',{'name':'test.png','content':base64.b64encode(b'not an image').decode()})[0],400)

    def test_mcp_protocol_and_schema(self):
        script=Path(__file__).resolve().parents[1]/'src/mcp_server.py'
        calls='\n'.join(json.dumps(x) for x in [
            {'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05'}},
            {'jsonrpc':'2.0','method':'notifications/initialized'},
            {'jsonrpc':'2.0','id':2,'method':'tools/list'}])+'\n'
        proc=subprocess.run([sys.executable,'-I',str(script)],input=calls,capture_output=True,text=True,encoding='utf-8',timeout=20)
        self.assertEqual(proc.returncode,0,proc.stderr)
        rows=[json.loads(line) for line in proc.stdout.splitlines()]
        self.assertEqual(len(rows),2)
        generate=next(t for t in rows[1]['result']['tools'] if t['name']=='generate_video')
        self.assertIn('shot',generate['inputSchema']['required'])

if __name__=='__main__': unittest.main()
