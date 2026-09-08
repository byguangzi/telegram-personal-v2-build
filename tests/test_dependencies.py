import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('dependencies', Path(__file__).parents[1] / 'ci/dependencies.py')
deps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deps)

class TransferTests(unittest.TestCase):
    def test_roundtrip_identity_hash_and_allowlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'original'
            for directory in ('Libraries/win64/cache_keys', 'ThirdParty/cache_keys', 'tdesktop'):
                (root / directory).mkdir(parents=True)
            for name in ('Qt5Core.lib', 'tg_owt.lib', 'libssl.lib', 'libcrypto.lib'):
                (root / 'Libraries/win64' / name).write_bytes(b'synthetic-public-library')
            (root / 'tdesktop/private-header.h').write_text('SYNTHETIC-MUST-NOT-TRANSFER')
            transfer = Path(tmp) / 'transfer'
            meta = {'source': 'fixed', 'sdk': 'fixed', 'path': 'fixed'}
            deps.pack(root, transfer, meta)
            restored = Path(tmp) / 'restored'
            deps.unpack(restored, transfer, meta)
            self.assertFalse((restored / 'tdesktop').exists())
            self.assertEqual((root / 'Libraries/win64/libssl.lib').read_bytes(), (restored / 'Libraries/win64/libssl.lib').read_bytes())
            with self.assertRaisesRegex(RuntimeError, 'identity'):
                deps.unpack(Path(tmp) / 'wrong', transfer, {'source': 'different'})
            with (transfer / 'dependencies.tar.gz').open('ab') as stream:
                stream.write(b'corruption')
            with self.assertRaisesRegex(RuntimeError, 'hash/size'):
                deps.unpack(Path(tmp) / 'broken', transfer, meta)

    def test_traversal_rejected_before_extract(self):
        with tempfile.TemporaryDirectory() as tmp:
            transfer = Path(tmp)
            archive = transfer / 'dependencies.tar.gz'
            with tarfile.open(archive, 'w:gz') as tar:
                info = tarfile.TarInfo('Libraries/../../escape'); info.size = 1
                tar.addfile(info, io.BytesIO(b'x'))
            (transfer / 'dependencies.json').write_text(json.dumps({'format': 1, 'identity': {}, 'bytes': archive.stat().st_size, 'sha256': deps.sha256(archive)}))
            with self.assertRaisesRegex(RuntimeError, 'Unsafe'):
                deps.unpack(transfer / 'dest', transfer, {})
            self.assertFalse((transfer / 'escape').exists())

if __name__ == '__main__': unittest.main()
