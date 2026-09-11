"""Strictly rebase the personal patch onto the latest official stable release."""
import hashlib,json,os,pathlib,re,subprocess,tempfile,urllib.request,uuid

ROOT=pathlib.Path(__file__).resolve().parents[1]
OFFICIAL='telegramdesktop/tdesktop'

def api(path, data=None):
    headers={'Accept':'application/vnd.github+json','User-Agent':'Telegram-Personal-Follower'}
    if os.environ.get('GH_TOKEN'): headers['Authorization']='Bearer '+os.environ['GH_TOKEN']
    request=urllib.request.Request('https://api.github.com/'+path,
        data=None if data is None else json.dumps(data).encode(),headers=headers)
    with urllib.request.urlopen(request,timeout=60) as response:
        body=response.read()
        return json.loads(body) if body else None

def git(cwd,*args):
    return subprocess.check_output(['git','-c','core.autocrlf=false','-C',str(cwd),*args])

def version_tuple(value):
    if not re.fullmatch(r'\d+\.\d+\.\d+',value): raise ValueError('Not a stable version')
    return tuple(map(int,value.split('.')))

def upgrade(source,commit,version):
    config=json.loads((ROOT/'kit.json').read_text(encoding='utf-8-sig'))
    if version_tuple(version)<=version_tuple(config['source_version']): return False
    if git(source,'rev-parse','HEAD').decode().strip()!=commit: raise RuntimeError('Source pin mismatch')
    header=(source/'Telegram/SourceFiles/core/version.h').read_text()
    if f'AppVersionStr = "{version}"' not in header: raise RuntimeError('Official version mismatch')
    patch=ROOT/config['patch_file']
    git(source,'apply','--check','--whitespace=error',str(patch))
    git(source,'apply','--whitespace=error',str(patch))
    for path in config['new_files']: git(source,'add','-N',path)
    git(source,'diff','--check')
    changed=git(source,'diff','--name-only').decode().splitlines()
    if sorted(changed)!=sorted(config['changed_files']): raise RuntimeError('Unexpected patch file set')
    updated=git(source,'diff','--binary','--full-index','--no-ext-diff')
    blobs={path:git(source,'rev-parse','HEAD:'+path).decode().strip()
           for path in config['baseline_blobs']}
    config.update(source_version=version,source_commit=commit,
                  source_tree=git(source,'rev-parse','HEAD^{tree}').decode().strip(),
                  baseline_blobs=blobs,patch_sha256=hashlib.sha256(updated).hexdigest())
    patch.write_bytes(updated)
    (ROOT/'kit.json').write_text(json.dumps(config,indent=2)+'\n')
    manifest=json.loads((ROOT/'SHA256SUMS.json').read_text())
    for name in ('kit.json',config['patch_file']):
        manifest[name]=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
    (ROOT/'SHA256SUMS.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return True

def main():
    repo=os.environ['GITHUB_REPOSITORY']
    if repo!='byguangzi/telegram-personal-v2-build': raise RuntimeError('Unexpected destination repository')
    release=api(f'repos/{OFFICIAL}/releases/latest')
    if release['draft'] or release['prerelease']: raise RuntimeError('Not a stable release')
    tag=release['tag_name']
    if not re.fullmatch(r'v\d+\.\d+\.\d+',tag): raise RuntimeError('Unexpected official tag')
    config=json.loads((ROOT/'kit.json').read_text())
    if version_tuple(tag[1:])<=version_tuple(config['source_version']):
        print('No newer stable version.'); return
    runs=api(f'repos/{repo}/actions/workflows/build-v22.yml/runs?per_page=100')['workflow_runs']
    if any(run['status']!='completed' for run in runs):
        print('Build active; defer upgrade until the next check.'); return
    ref=api(f'repos/{OFFICIAL}/git/ref/tags/{tag}')['object']
    for _ in range(5):
        if ref['type']=='commit': break
        if ref['type']!='tag': raise RuntimeError('Unexpected reference type')
        ref=api(f'repos/{OFFICIAL}/git/tags/{ref["sha"]}')['object']
    if ref['type']!='commit': raise RuntimeError('Tag nesting exceeded')
    with tempfile.TemporaryDirectory() as temp:
        source=pathlib.Path(temp)
        git(source,'init','-q')
        git(source,'remote','add','origin','https://github.com/'+OFFICIAL+'.git')
        git(source,'fetch','--depth=1','origin',ref['sha'])
        git(source,'checkout','--detach','FETCH_HEAD')
        upgrade(source,ref['sha'],tag[1:])
    git(ROOT,'config','user.name','github-actions[bot]')
    git(ROOT,'config','user.email','41898282+github-actions[bot]@users.noreply.github.com')
    git(ROOT,'add','kit.json',config['patch_file'],'SHA256SUMS.json')
    git(ROOT,'commit','-m','Prepare Telegram '+tag[1:]+' personal candidate')
    branch=os.environ['DEFAULT_BRANCH']
    git(ROOT,'push','origin','HEAD:refs/heads/'+branch)
    commit=git(ROOT,'rev-parse','HEAD').decode().strip()
    api(f'repos/{repo}/actions/workflows/build-v22.yml/dispatches',
        {'ref':branch,'inputs':{'request_id':'auto-'+uuid.uuid4().hex,'kit_commit':commit}})
    print('Candidate build dispatched for '+tag+' at '+commit)

if __name__=='__main__': main()
