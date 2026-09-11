"""Publish verified build files as a draft; never auto-promote untested runtime code."""
import hashlib,json,os,pathlib,urllib.request
from follow_upstream import api

def main():
    repo=os.environ['GITHUB_REPOSITORY']
    artifact=pathlib.Path('artifact')
    info=json.loads((artifact/'build-info.json').read_text())
    config=json.loads(pathlib.Path('kit.json').read_text())
    if info['source_commit']!=config['source_commit'] or info['configuration']!='Release':
        raise RuntimeError('Candidate provenance mismatch')
    digest=hashlib.sha256((artifact/'Telegram.exe').read_bytes()).hexdigest()
    if digest!=info['sha256']: raise RuntimeError('Candidate EXE hash mismatch')
    tag='personal-'+config['source_version']+'-'+os.environ['GITHUB_RUN_ID']+'-'+os.environ['GITHUB_RUN_ATTEMPT']
    release=api(f'repos/{repo}/releases',{
        'tag_name':tag,'target_commitish':os.environ['GITHUB_SHA'],
        'name':'Telegram Personal '+config['source_version']+' candidate',
        'draft':True,'prerelease':False,
        'body':'Windows x64 Release. Build and SHA-256 verified. Runtime acceptance pending: '
               'existing tdata login, MTProto, direct fallback, permanent archive and mute. '
               'Do not distribute as an automatic update before acceptance.\n\nSHA-256: '+digest})
    upload=release['upload_url'].split('{')[0]
    for name in ('Telegram.exe','Telegram.exe.sha256','build-info.json'):
        request=urllib.request.Request(upload+'?name='+name,data=(artifact/name).read_bytes(),
            headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],
                     'Content-Type':'application/octet-stream'},method='POST')
        with urllib.request.urlopen(request,timeout=180) as response:response.read()
    print('Draft candidate uploaded; no stable update was published.')

if __name__=='__main__':main()
