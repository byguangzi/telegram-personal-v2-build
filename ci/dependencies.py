"""Transfer only public dependencies between jobs, before private configuration exists."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sys
import tarfile

ROOTS = ('Libraries', 'ThirdParty')

def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def identity():
    return {key: os.environ[key] for key in
            ('SOURCE_COMMIT', 'SDK', 'VCToolsVersion', 'BUILD_STORAGE', 'CACHE_KEY')}

def verify_libraries(root):
    for name in ('Qt5Core.lib', 'tg_owt.lib', 'libssl.lib', 'libcrypto.lib'):
        if not any(p.is_file() and p.stat().st_size for p in (root / 'Libraries').rglob(name)):
            raise RuntimeError('Prepared dependency is missing: ' + name)
    for name in ('Libraries/win64/cache_keys', 'ThirdParty/cache_keys'):
        if not (root / name).is_dir():
            raise RuntimeError('Dependency completion metadata missing: ' + name)

def pack(root, output, meta):
    verify_libraries(root)
    output.mkdir(parents=True, exist_ok=False)
    archive = output / 'dependencies.tar.gz'
    count = 0
    def public_only(info):
        nonlocal count
        parts = PurePosixPath(info.name).parts
        if '.git' in parts or '__pycache__' in parts:
            return None
        path = root.joinpath(*parts)
        actual = path.resolve()
        if not any(actual.is_relative_to((root / name).resolve()) for name in ROOTS):
            raise RuntimeError('Dependency link points outside the public dependency roots.')
        if info.isdir() and any(actual == parent.resolve() for parent in path.parents):
            raise RuntimeError('Dependency directory link forms a cycle.')
        if not info.isdir() and not info.isfile():
            raise RuntimeError('Unsupported dependency link/special file: ' + info.name)
        count += 1
        return info
    # Store linked files as bytes, independent of Windows symlink privileges on restore.
    with tarfile.open(archive, 'w:gz', compresslevel=1, dereference=True) as tar:
        for name in ROOTS:
            tar.add(root / name, arcname=name, filter=public_only)
    manifest = {'format': 1, 'identity': meta, 'sha256': sha256(archive),
                'bytes': archive.stat().st_size, 'entries': count}
    (output / 'dependencies.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(f'Dependencies saved: {count} entries; {archive.stat().st_size / 2**30:.2f} GiB; SHA-256 {manifest["sha256"]}')

def unpack(root, source, meta):
    archive = source / 'dependencies.tar.gz'
    manifest = json.loads((source / 'dependencies.json').read_text(encoding='utf-8'))
    if manifest.get('format') != 1 or manifest.get('identity') != meta:
        raise RuntimeError('Dependency source/toolchain/SDK/path identity mismatch.')
    if archive.stat().st_size != manifest['bytes'] or sha256(archive) != manifest['sha256']:
        raise RuntimeError('Dependency archive hash/size mismatch.')
    with tarfile.open(archive, 'r:gz') as tar:
        for info in tar:
            name = PurePosixPath(info.name)
            if (name.is_absolute() or '..' in name.parts or not name.parts
                    or name.parts[0] not in ROOTS or '\\' in info.name or ':' in info.name
                    or (not info.isdir() and not info.isfile())):
                raise RuntimeError('Unsafe dependency archive member.')
            dest = root.joinpath(*name.parts)
            if not dest.resolve().is_relative_to(root.resolve()):
                raise RuntimeError('Dependency archive escaped build root.')
            if dest.exists() and not (info.isdir() and dest.is_dir()):
                raise RuntimeError('Dependency restore would overwrite existing data.')
        tar.extractall(root, filter='data')
    verify_libraries(root)
    print('PASS: verified dependencies restored; no dependency compilation in this job.')

if __name__ == '__main__':
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise SystemExit('This transfer entry point is restricted to GitHub Actions.')
    root = Path(os.environ['BUILD_STORAGE'])
    output = Path(os.environ['GITHUB_WORKSPACE']) / 'dependency-transfer'
    if sys.argv[1:] == ['pack']:
        pack(root, output, identity())
    elif sys.argv[1:] == ['unpack']:
        unpack(root, output, identity())
        (output / 'dependencies.tar.gz').unlink()
        (output / 'dependencies.json').unlink()
    else:
        raise SystemExit('Expected pack or unpack.')
