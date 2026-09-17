"""Regression gates for scheduling/cache changes; no Telegram feature changes."""
import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ci'))
import build_tuning as tuning
import dependency_cache as deps_cache
import plan_build


class SchedulingTests(unittest.TestCase):
    def test_resource_limits_and_safe_mode(self):
        gib = 1024 ** 3
        self.assertEqual(tuning.select_workers('auto', 4, 12*gib, 16*gib), 2)
        for mode, cpus, ram, commit in [('safe', 8, 32, 64), ('auto', 1, 32, 64),
                                       ('auto', 8, 9, 64), ('auto', 8, 32, 11),
                                       ('auto', None, 0, 0)]:
            self.assertEqual(tuning.select_workers(mode, cpus, ram*gib, commit*gib), 1)
        with self.assertRaises(ValueError):
            tuning.select_workers('fastest', 64, 999*gib, 999*gib)

    def test_only_parallelism_option_changes(self):
        with mock.patch.dict(os.environ, {'_CL_': '/O2 /MP8 /DKEEP_THIS=1'}, clear=False):
            tuning.configure_workers(2)
            self.assertEqual(os.environ['_CL_'], '/O2  /DKEEP_THIS=1 /MP2')
            self.assertEqual(os.environ['CMAKE_BUILD_PARALLEL_LEVEL'], '1')
            tuning.configure_workers(1)
            self.assertNotIn('/MP2', os.environ['_CL_'])
            self.assertIn('/MP1', os.environ['_CL_'])
        for n in (1, 2):
            command = tuning.build_command(Path('source'), n)
            self.assertEqual(command[command.index('--config') + 1], 'Release')
            self.assertEqual(command[command.index('--parallel') + 1], '1')
            self.assertEqual(command[command.index('--target') + 1], 'Telegram')

    def test_retry_is_not_for_source_or_link_errors(self):
        for text in ('fatal error C1060: exhausted', 'C1076', 'C3859', 'LNK1102'):
            self.assertTrue(tuning.resource_error(text))
        for text in ('error C2039: member not found', 'error LNK2019', 'C10600', 'network failed'):
            self.assertFalse(tuning.resource_error(text))

    def run_fake_build(self, first_result, first_output, retry_result=0):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'tdesktop/out').mkdir(parents=True)
            (root/'tdesktop/Telegram').mkdir()
            (root/'tdesktop/out/CMakeCache.txt').write_text(
                'CMAKE_CONFIGURATION_TYPES:STRING=Release\n'
                'DESKTOP_APP_DISABLE_AUTOUPDATE:BOOL=ON\n'
                'DESKTOP_APP_DISABLE_CRASH_REPORTS:BOOL=ON\n')
            env = {'TBUILD': str(root), 'GITHUB_WORKSPACE': str(ROOT), 'BUILD_MODE': 'auto',
                   'TDESKTOP_API_ID': '1234567', 'TDESKTOP_API_HASH': 'a'*32,
                   'PRECONFIGURED_PROXY_HOST': 'synthetic.invalid', 'PRECONFIGURED_PROXY_PORT': '443',
                   'PRECONFIGURED_PROXY_SECRET': 'b'*32}
            calls = []
            class Process:
                def __init__(self, args, **kwargs):
                    calls.append((args, os.environ.get('_CL_', '')))
                    number = len(calls)
                    self.code = 0 if number == 1 else (first_result if number == 2 else retry_result)
                    self.stdout = io.StringIO(first_output if number == 2 else 'done\n')
                def wait(self): return self.code
            captured = io.StringIO()
            error = None
            with mock.patch.dict(os.environ, env), mock.patch.object(tuning, 'available_memory', return_value=(20*1024**3, 30*1024**3)), \
                    mock.patch('os.cpu_count', return_value=4), mock.patch('subprocess.Popen', Process), contextlib.redirect_stdout(captured):
                try:
                    runpy.run_path(str(ROOT/'ci/build.py'), run_name='__main__')
                except SystemExit as exc:
                    error = exc
            return calls, error, captured.getvalue()

    def test_memory_failure_retries_original_serial_once(self):
        calls, error, output = self.run_fake_build(1, 'fatal error C1060\n')
        self.assertIsNone(error)
        self.assertEqual(len(calls), 3)
        self.assertIn('/MP2', calls[1][1])
        self.assertIn('/MP1', calls[2][1])
        self.assertIn('/p:MultiProcessorCompilation=false', calls[2][0])
        self.assertIn('retrying once', output)
        configure = calls[0][0]
        for flag in ('CMAKE_CONFIGURATION_TYPES=Release', 'CMAKE_MSVC_DEBUG_INFORMATION_FORMAT=',
                     'DESKTOP_APP_DISABLE_AUTOUPDATE=ON', 'DESKTOP_APP_DISABLE_CRASH_REPORTS=ON'):
            self.assertIn(flag, configure)

    def test_real_errors_fail_and_secrets_still_redacted(self):
        calls, error, output = self.run_fake_build(1, 'error C2039 synthetic.invalid ' + 'b'*32 + '\n')
        self.assertIsNotNone(error)
        self.assertEqual(len(calls), 2)
        self.assertNotIn('synthetic.invalid', output)
        self.assertNotIn('b'*32, output)
        self.assertIn('[REDACTED]', output)

    def test_failed_serial_retry_is_not_accepted(self):
        calls, error, _ = self.run_fake_build(1, 'C3859\n', retry_result=1)
        self.assertIsNotNone(error)
        self.assertEqual(len(calls), 3)


class DependencySeedTests(unittest.TestCase):
    def test_missing_cache_identity_falls_back_to_cold_without_failing_build(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root/'env'
            env = {'GITHUB_ACTIONS':'true','BUILD_STORAGE':temp,'TBUILD':temp,
                   'RUNNER_TEMP':temp,'GITHUB_ENV':str(output)}
            with mock.patch.dict(os.environ,env), mock.patch.object(sys,'argv',['dependency_cache.py','keys']), \
                    mock.patch.object(deps_cache,'cache_keys',side_effect=ValueError('missing identity')), \
                    contextlib.redirect_stdout(io.StringIO()):
                deps_cache.main()
            self.assertIn('DEPENDENCY_CACHE_ENABLED=false',output.read_text())

    def test_cold_reference_build_never_uses_existing_handoff(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'kit.json').write_text(json.dumps({'source_commit':'a'*40,'source_version':'7.2.9'}))
            output = root/'output'
            env = {'REQUEST_COMMIT':'b'*40,'GITHUB_SHA':'b'*40,'GITHUB_REPOSITORY':'owner/repo',
                   'GITHUB_OUTPUT':str(output),'DEPENDENCY_CACHE_MODE':'cold',
                   'REQUEST_DEPENDENCY_RUN':'','REQUEST_DEPENDENCY_ARTIFACT':''}
            with mock.patch.object(plan_build,'ROOT',root), mock.patch.object(plan_build,'api') as api, \
                    mock.patch.dict(os.environ,env), contextlib.redirect_stdout(io.StringIO()):
                plan_build.main()
                api.assert_not_called()
                self.assertIn('dependency_run=\n',output.read_text())
                with mock.patch.dict(os.environ,{'REQUEST_DEPENDENCY_RUN':'100','REQUEST_DEPENDENCY_ARTIFACT':'200'}):
                    with self.assertRaises(RuntimeError):plan_build.main()

    def test_recipes_reuse_engine_but_engine_changes_invalidate(self):
        source = "def checkCacheKey(stage):\n    return stage['key']\nstage('qt', 'old recipe')\n"
        engine = deps_cache.engine_digest(source, {'win.bat': b'prepare silent'})
        self.assertEqual(engine, deps_cache.engine_digest(source.replace('old recipe','new recipe'), {'win.bat': b'prepare silent'}))
        self.assertNotEqual(engine, deps_cache.engine_digest(source.replace("stage['key']", "'bad'"), {'win.bat': b'prepare silent'}))
        self.assertNotEqual(engine, deps_cache.engine_digest(source, {'win.bat': b'different runner'}))

    def test_toolchain_image_and_path_changes_never_share_seed_prefix(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            prepare = source/'Telegram/build/prepare/prepare.py'
            prepare.parent.mkdir(parents=True)
            prepare.write_text("stage('qt', 'old')\n")
            (prepare.parent/'win.bat').write_text('prepare')
            (prepare.parent.parent/'qt_version.py').write_text('qt=5')
            env = {'SDK':'10.0.test', 'VCToolsVersion':'14.44', 'BUILD_STORAGE':r'D:\Build',
                   'ImageOS':'win25', 'ImageVersion':'v1', 'Platform':'x64', 'VSCMD_ARG_HOST_ARCH':'x64'}
            prefix, recipe = deps_cache.cache_keys(source, env)
            prepare.write_text("stage('qt', 'changed')\n")
            new_prefix, new_recipe = deps_cache.cache_keys(source, env)
            self.assertEqual(prefix, new_prefix)
            self.assertNotEqual(recipe, new_recipe)
            for field in ('SDK','VCToolsVersion','BUILD_STORAGE','ImageOS','ImageVersion'):
                self.assertNotEqual(prefix, deps_cache.cache_keys(source, dict(env, **{field:'different'}))[0])
            for field in env:
                with self.assertRaises(ValueError):
                    deps_cache.cache_keys(source, dict(env, **{field:''}))

    def test_workflow_keeps_prepare_and_runtime_checks(self):
        text = (ROOT/'.github/workflows/build-v22.yml').read_text()
        preparation = text.split('      - name: Prepare official libraries with Release enabled\n')[1].split('      - name:')[0]
        self.assertNotIn('if:', preparation)
        self.assertIn('win.bat" silent', preparation)
        self.assertEqual(text.count('restore-keys:'), 3)
        self.assertIn('manifest.identity.SOURCE_COMMIT -ne $env:SOURCE_COMMIT', text)
        self.assertIn('ci\\generate_proxy.py', text)
        self.assertIn('ci\\stage.py', text)
        self.assertIn('cancel-in-progress: false', text)
        self.assertNotIn('CXX_COMPILER_LAUNCHER', text)


if __name__ == '__main__':
    unittest.main()
