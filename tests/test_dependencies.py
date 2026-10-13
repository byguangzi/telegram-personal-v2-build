import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest import mock
import os

spec = importlib.util.spec_from_file_location('dependencies', Path(__file__).parents[1] / 'ci/dependencies.py')
deps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deps)

class TransferTests(unittest.TestCase):
    def seed(self, root):
        for directory in ('Libraries/win64/cache_keys', 'ThirdParty/cache_keys',
                          'ThirdParty/msys64/etc'):
            (root / directory).mkdir(parents=True)
        for name in ('Qt5Core.lib', 'tg_owt.lib', 'libssl.lib', 'libcrypto.lib'):
            (root / 'Libraries/win64' / name).write_bytes(b'public-library-' + name.encode())
        (root / 'ThirdParty/msys64/etc/fstab').write_bytes(b'keep-mount-configuration')

    def test_inaccessible_mtab_is_skipped_before_stat_and_roundtrips(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'original'
            self.seed(root)
            mtab = root / 'ThirdParty/msys64/etc/mtab'
            mtab.write_bytes(b'host-specific-placeholder')
            transfer = Path(tmp) / 'transfer'
            real_stat = os.stat
            touched = []
            def guarded_stat(path, *args, **kwargs):
                if not isinstance(path, int) and os.path.normpath(os.fspath(path)) == str(mtab):
                    touched.append(path)
                    error = OSError('The file cannot be accessed by the system')
                    error.winerror = 1920
                    raise error
                return real_stat(path, *args, **kwargs)
            with mock.patch.object(os, 'stat', side_effect=guarded_stat):
                deps.pack(root, transfer, {})
            self.assertEqual(touched, [])
            self.assertEqual(mtab.read_bytes(), b'host-specific-placeholder')
            restored = Path(tmp) / 'restored'
            deps.unpack(restored, transfer, {})
            self.assertFalse((restored / 'ThirdParty/msys64/etc/mtab').exists())
            self.assertEqual((restored / 'ThirdParty/msys64/etc/fstab').read_bytes(),
                             b'keep-mount-configuration')
            for name in ('Qt5Core.lib', 'tg_owt.lib', 'libssl.lib', 'libcrypto.lib'):
                self.assertEqual((root / 'Libraries/win64' / name).read_bytes(),
                                 (restored / 'Libraries/win64' / name).read_bytes())

    def test_unrelated_unreadable_file_still_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'original'
            self.seed(root)
            bad = root / 'ThirdParty/msys64/etc/fstab'
            real_stat = os.stat
            def guarded_stat(path, *args, **kwargs):
                if not isinstance(path, int) and os.path.normpath(os.fspath(path)) == str(bad):
                    raise OSError('synthetic access failure')
                return real_stat(path, *args, **kwargs)
            with mock.patch.object(os, 'stat', side_effect=guarded_stat):
                with self.assertRaisesRegex(OSError, 'synthetic access failure'):
                    deps.pack(root, Path(tmp) / 'transfer', {})

    def test_other_mtab_paths_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'original'
            self.seed(root)
            for name in ('Libraries/mtab', 'ThirdParty/mtab',
                         'ThirdParty/msys64/etc/mtab.backup'):
                (root / name).write_bytes(b'not-the-runtime-mount-table')
            transfer = Path(tmp) / 'transfer'
            deps.pack(root, transfer, {})
            with tarfile.open(transfer / 'dependencies.tar.gz') as tar:
                for name in ('Libraries/mtab', 'ThirdParty/mtab',
                             'ThirdParty/msys64/etc/mtab.backup'):
                    self.assertEqual(tar.extractfile(name).read(), b'not-the-runtime-mount-table')

    def test_external_link_still_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'original'
            self.seed(root)
            outside = Path(tmp) / 'private.txt'
            outside.write_bytes(b'must-not-transfer')
            try:
                (root / 'ThirdParty/outside').symlink_to(outside)
            except OSError as error:
                self.skipTest('Host cannot create test symlinks: ' + str(error))
            with self.assertRaisesRegex(RuntimeError, 'outside the public'):
                deps.pack(root, Path(tmp) / 'transfer', {})

    def test_broken_mtab_link_skipped_other_links_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'original'
            self.seed(root)
            try:
                (root / 'ThirdParty/msys64/etc/mtab').symlink_to('/nonexistent-proc-mounts')
                (root / 'ThirdParty/internal-lib').symlink_to(root / 'Libraries/win64/libssl.lib')
            except OSError as error:
                self.skipTest('Host cannot create test symlinks: ' + str(error))
            transfer = Path(tmp) / 'transfer'
            deps.pack(root, transfer, {})
            with tarfile.open(transfer / 'dependencies.tar.gz') as tar:
                self.assertNotIn('ThirdParty/msys64/etc/mtab', tar.getnames())
                self.assertTrue(tar.getmember('ThirdParty/internal-lib').isfile())
                self.assertEqual(tar.extractfile('ThirdParty/internal-lib').read(),
                                 (root / 'Libraries/win64/libssl.lib').read_bytes())

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
