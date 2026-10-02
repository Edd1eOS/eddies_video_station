import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from core import Station, validate_shot, workflow, prompt_text, MANIFEST


class CoreTests(unittest.TestCase):
    def test_defaults_and_limits(self):
        self.assertEqual(validate_shot({'prompt':'hello'})['frames'],33)
        for extra in ({'width':257},{'frames':32},{'seed':-1},{'cfg':float('nan')},{'profile':'unknown'},{'image':'x.png'}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                validate_shot({'prompt':'hello',**extra})

    def test_graph_text_and_reference(self):
        text=workflow({'prompt':'boat'},'test')
        self.assertEqual(text['6']['class_type'],'EmptyHunyuanLatentVideo')
        image=workflow({'prompt':'boat','profile':'wan5','image':'boat.png','loras':[{'file':'test.safetensors','weight':.7}]},'test')
        self.assertEqual(image['6']['inputs']['start_image'],['12',0])
        self.assertEqual(image['7']['inputs']['model'],['20',0])
        self.assertEqual(image['20']['inputs']['strength_model'],.7)

    def test_tag_semantics(self):
        text=prompt_text('boat',[{'text':'red','weight':0},{'text':'daylight','weight':1.5}])
        self.assertNotIn('red',text)
        self.assertIn('Emphasize: daylight',text)

    def test_persistence_recovery_and_cancel(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=Station(tmp)
            p=s.save_project({'name':'test'})
            self.assertEqual(s.projects()[0]['id'],p['id'])
            job=s.submit({'project':p['id'],'shot':{'prompt':'boat'}})
            s.cancel_job(job['id'])
            self.assertEqual(s.jobs()[0]['state'],'cancelled')
            s.submit({'shot':{'prompt':'boat'}})
            restarted=Station(tmp)
            self.assertEqual(restarted.jobs()[0]['state'],'failed')

    def test_path_and_project_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=Station(tmp)
            with self.assertRaises(ValueError): s.save_project({'id':'<script>'})
            with self.assertRaises(ValueError): s.submit({'shot':{'prompt':'boat','profile':'wan5','image':'../outside.png'}})
            with self.assertRaises(ValueError): s.submit({'shot':{'prompt':'boat','loras':[{'file':'../bad.safetensors'}]}})
            s.submit({'shot':{'prompt':'boat'}})
            with self.assertRaises(ValueError): s.settings({'data_root':str(Path(tmp)/'another')})
            self.assertEqual(s.settings({'data_root':tmp})['data_root'],str(Path(tmp).resolve()))

    def test_verified_file_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=Station(tmp); p=s.data/'models/test.bin'; p.write_bytes(b'abc')
            f={'path':'test.bin','size':3,'sha256':'testhash'}
            self.assertFalse(s.file_ready(f))
            p.with_suffix('.verified').write_text('testhash')
            self.assertTrue(s.file_ready(f))
            p.with_suffix('.verified').write_text('wrong')
            self.assertFalse(s.file_ready(f))

    def test_manifest_locks(self):
        for f in MANIFEST['files'].values():
            self.assertEqual(len(f['sha256']),64)
            self.assertEqual(len(f['revision']),40)
            self.assertGreater(f['size'],0)

    def test_cancel_during_engine_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=Station(tmp); s.active='starting'; s.process=object()
            with patch('core.request',side_effect=ConnectionRefusedError):
                self.assertTrue(s.cancel_job('starting')['ok'])
            self.assertIn('starting',s.cancel)

if __name__=='__main__': unittest.main()
