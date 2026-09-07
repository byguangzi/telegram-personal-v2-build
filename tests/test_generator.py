import base64,importlib.util,pathlib,unittest
p=pathlib.Path(__file__).resolve().parents[1]/'ci/generate_proxy.py'
s=importlib.util.spec_from_file_location('generator',p); m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class GeneratorTests(unittest.TestCase):
    def test_supported_secrets(self):
        for raw in (bytes(range(16)),b'\xdd'+bytes(range(16)),b'\xee'+bytes(range(16))+b'example.org'):
            for encoded in (raw.hex(),raw.hex().upper(),base64.urlsafe_b64encode(raw).decode().rstrip('=')):
                self.assertEqual(m.normalize_mtproto_secret(encoded),raw.hex())
    def test_rejects_bad_inputs(self):
        for text in ('','1234','zz!!','00'*17,'dd'+'00'*14,'ee'+'00'*17,'A','abc\n123'):
            with self.subTest(text=text),self.assertRaises(SystemExit):m.normalize_mtproto_secret(text)
if __name__=='__main__':unittest.main()
