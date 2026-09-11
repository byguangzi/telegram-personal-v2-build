"""Select a completed dependency handoff only for identical dependency inputs."""
import base64,json,os,pathlib,re
from follow_upstream import api

ROOT=pathlib.Path(__file__).resolve().parents[1]

def compatible(config,other,manifest,previous):
    return (config['source_commit']==other.get('source_commit')
            and all(manifest.get(p)==previous.get(p) and manifest.get(p)
                    for p in ('ci/dependencies.py','ci/storage.ps1','ci/ensure-atl.ps1')))

def main():
    if os.environ['REQUEST_COMMIT']!=os.environ['GITHUB_SHA']:
        raise RuntimeError('Build kit moved; refresh before dispatch.')
    config=json.loads((ROOT/'kit.json').read_text())
    if not re.fullmatch(r'[a-f0-9]{40}',config['source_commit']): raise RuntimeError('Bad source pin')
    if not re.fullmatch(r'\d+\.\d+\.\d+',config['source_version']): raise RuntimeError('Bad source version')
    repo=os.environ['GITHUB_REPOSITORY']
    run_id=os.environ.get('REQUEST_DEPENDENCY_RUN','')
    artifact_id=os.environ.get('REQUEST_DEPENDENCY_ARTIFACT','')
    if bool(run_id)!=bool(artifact_id): raise RuntimeError('Both dependency IDs are required together')
    if not run_id:
        artifacts=api(f'repos/{repo}/actions/artifacts?per_page=100')['artifacts']
        manifest=json.loads((ROOT/'SHA256SUMS.json').read_text())
        for item in artifacts:
            if item['expired'] or not re.fullmatch(r'Public-dependencies-\d+-\d+',item['name']): continue
            run=item.get('workflow_run',{})
            if not run.get('head_sha'): continue
            previous={}
            for name in ('kit.json','SHA256SUMS.json'):
                data=api(f'repos/{repo}/contents/{name}?ref={run["head_sha"]}')
                previous[name]=json.loads(base64.b64decode(data['content']))
            if not compatible(config,previous['kit.json'],manifest,previous['SHA256SUMS.json']): continue
            status=api(f'repos/{repo}/actions/runs/{run["id"]}')
            if status['status']!='completed' or status['path']!='.github/workflows/build-v22.yml': continue
            if item['name']!=f'Public-dependencies-{run["id"]}-{status["run_attempt"]}': continue
            run_id=str(run['id']);artifact_id=str(item['id']);break
    values={'source':config['source_commit'],'version':config['source_version'],
            'dependency_run':run_id,'dependency_artifact':artifact_id}
    with open(os.environ['GITHUB_OUTPUT'],'a') as f:
        for key,value in values.items():
            if '\n' in value or '\r' in value: raise RuntimeError('Invalid output')
            f.write(key+'='+value+'\n')
    print('Plan: Telegram '+config['source_version']+'; '+
          ('reuse completed dependency run '+run_id if run_id else 'prepare dependencies'))

if __name__=='__main__':main()
