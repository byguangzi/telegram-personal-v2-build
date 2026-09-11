import hashlib,importlib.util,json,pathlib,subprocess,sys,tempfile,unittest
CI=pathlib.Path(__file__).resolve().parents[1]/'ci'
sys.path.insert(0,str(CI))
import follow_upstream as follow
import plan_build as plan

class UpgradeTests(unittest.TestCase):
    def test_numeric_stable_versions(self):
        self.assertGreater(follow.version_tuple('7.2.10'),follow.version_tuple('7.2.8'))
        for invalid in ('v7.2.8','7.2.8-beta','7.2.8\n'):
            with self.assertRaises(ValueError):follow.version_tuple(invalid)

    def test_dependency_identity(self):
        a={'source_commit':'a'}
        manifest={p:'sha' for p in ('ci/dependencies.py','ci/storage.ps1','ci/ensure-atl.ps1')}
        self.assertTrue(plan.compatible(a,a,manifest,manifest))
        self.assertFalse(plan.compatible(a,{'source_commit':'b'},manifest,manifest))
        self.assertFalse(plan.compatible(a,a,manifest,{}))

    def test_real_git_rebase_and_conflict(self):
        original_root=follow.ROOT
        with tempfile.TemporaryDirectory() as temp:
            source=pathlib.Path(temp)/'source';source.mkdir()
            kit=pathlib.Path(temp)/'kit';kit.mkdir()
            def git(*args):return follow.git(source,*args)
            git('init','-q');git('config','user.email','test@localhost');git('config','user.name','Test')
            git('config','core.safecrlf','false')
            version=source/'Telegram/SourceFiles/core/version.h';version.parent.mkdir(parents=True)
            version.write_text('AppVersionStr = "7.2.8"\n',newline='\n')
            f=source/'feature.cpp';f.write_text('one\ntwo\nthree\n',newline='\n')
            git('add','.');git('-c','commit.gpgsign=false','commit','-qm','baseline')
            f.write_text('one\npersonal\nthree\n',newline='\n')
            patch=git('diff','--full-index')
            f.write_text('one\ntwo\nthree\n',newline='\n')
            cfg={'source_version':'7.2.8','patch_file':'personal.patch','new_files':[],
                 'changed_files':['feature.cpp'],'baseline_blobs':{'feature.cpp':'old'}}
            (kit/'kit.json').write_text(json.dumps(cfg));(kit/'personal.patch').write_bytes(patch)
            (kit/'SHA256SUMS.json').write_text('{}')
            version.write_text('AppVersionStr = "7.2.9"\n',newline='\n');git('add','.');git('-c','commit.gpgsign=false','commit','-qm','upgrade')
            sha=git('rev-parse','HEAD').decode().strip()
            follow.ROOT=kit
            try:
                self.assertTrue(follow.upgrade(source,sha,'7.2.9'))
                self.assertIn('personal',f.read_text())
                manifest=json.loads((kit/'SHA256SUMS.json').read_text())
                self.assertEqual(manifest['personal.patch'],hashlib.sha256((kit/'personal.patch').read_bytes()).hexdigest())
                version.write_text('AppVersionStr = "7.2.10"\n',newline='\n');f.write_text('incompatible\n',newline='\n')
                git('add','.');git('-c','commit.gpgsign=false','commit','-qm','conflict')
                before=(kit/'kit.json').read_bytes()
                with self.assertRaises(subprocess.CalledProcessError):
                    follow.upgrade(source,git('rev-parse','HEAD').decode().strip(),'7.2.10')
                self.assertEqual(before,(kit/'kit.json').read_bytes())
            finally:follow.ROOT=original_root

if __name__=='__main__':unittest.main()
