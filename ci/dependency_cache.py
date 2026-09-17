"""Restore compatible dependency seeds; upstream prepare ALWAYS revalidates them.

This is not permission to skip dependency preparation. Completed handoff artifacts
retain their exact SOURCE_COMMIT / toolchain / SDK / path identity checks.
No Telegram source, generated proxy/API configuration, or object files are cached.
"""
import ast
import hashlib
import json
import os
from pathlib import Path
import sys


class WithoutRecipes(ast.NodeTransformer):
    def visit_Expr(self, node):
        call = node.value
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == 'stage':
            # Recipes are rehashed per stage by OFFICIAL prepare.py, after restore.
            return ast.copy_location(ast.Pass(), node)
        return self.generic_visit(node)


def engine_digest(prepare_text, support_files):
    tree = WithoutRecipes().visit(ast.parse(prepare_text))
    payload = ast.dump(tree, include_attributes=False).encode()
    digest = hashlib.sha256(payload)
    for name, data in sorted(support_files.items()):
        digest.update(b'\0' + name.encode() + b'\0' + hashlib.sha256(data).digest())
    return digest.hexdigest()


def cache_keys(source, env):
    required = ('SDK', 'VCToolsVersion', 'BUILD_STORAGE', 'ImageOS', 'ImageVersion',
                'Platform', 'VSCMD_ARG_HOST_ARCH')
    values = {key: env.get(key, '') for key in required}
    if not all(values.values()):
        raise ValueError('Missing toolchain/image identity for dependency cache.')
    if values['Platform'].lower() != 'x64' or values['VSCMD_ARG_HOST_ARCH'].lower() != 'x64':
        raise ValueError('Dependency seed cache requires x64 target and host.')
    prepare = source / 'Telegram/build/prepare/prepare.py'
    support = {}
    for path in sorted(prepare.parent.rglob('*')):
        if path.is_file() and path != prepare and '__pycache__' not in path.parts:
            support[path.relative_to(source).as_posix()] = path.read_bytes()
    for rel in ('Telegram/build/qt_version.py',):
        support[rel] = (source / rel).read_bytes()
    raw = prepare.read_bytes()
    values['engine'] = engine_digest(raw.decode('utf-8-sig'), support)
    # Bump this namespace whenever our trust/validation rules change.
    prefix = 'td-deps-seed-v1-' + hashlib.sha256(
        json.dumps(values, sort_keys=True).encode()).hexdigest()
    recipe = hashlib.sha256(raw).hexdigest()
    return prefix, recipe


def snapshot(root):
    result = {}
    for rel in ('Libraries/win64/cache_keys', 'ThirdParty/cache_keys'):
        directory = root / rel
        if directory.is_dir():
            for path in directory.iterdir():
                if path.is_file():
                    result[path.relative_to(root).as_posix()] = path.read_text().strip()
    return result


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise SystemExit('Dependency cache entry point is restricted to GitHub Actions.')
    root = Path(os.environ['BUILD_STORAGE'])
    source = Path(os.environ['TBUILD']) / 'tdesktop'
    state = Path(os.environ['RUNNER_TEMP']) / 'telegram-dependency-keys-before.json'
    if sys.argv[1:] == ['keys']:
        enabled = True
        try:
            prefix, recipe = cache_keys(source, os.environ)
        except ValueError:
            # Missing identity must mean no cache, never a looser restore prefix.
            enabled = False
            prefix, recipe = 'td-deps-cache-disabled', 'disabled'
            print('::warning::Dependency toolchain identity incomplete; using a cold dependency build.')
        with open(os.environ['GITHUB_ENV'], 'a', encoding='utf-8') as output:
            output.write('DEPENDENCY_SEED_PREFIX=' + prefix + '\n')
            output.write('DEPENDENCY_RECIPE_HASH=' + recipe + '\n')
            output.write('DEPENDENCY_CACHE_ENABLED=' + ('true' if enabled else 'false') + '\n')
        if enabled:
            print('Dependency cache identity includes official engine, support scripts, image, compiler, SDK and path.')
    elif sys.argv[1:] == ['before']:
        state.write_text(json.dumps(snapshot(root)), encoding='utf-8')
    elif sys.argv[1:] == ['after']:
        before = json.loads(state.read_text(encoding='utf-8'))
        after = snapshot(root)
        reused = sum(before.get(key) == value for key, value in after.items())
        print('Official preparation completed: %d unchanged stage keys, %d new/changed stage keys.' %
              (reused, len(after) - reused))
        print('Key counts are diagnostics; they do not replace upstream validation or runtime testing.')
    else:
        raise SystemExit('Expected keys, before or after.')


if __name__ == '__main__':
    main()
