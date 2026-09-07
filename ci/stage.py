import hashlib,json,os,pathlib,struct,subprocess
root=pathlib.Path(os.environ['TBUILD'])/'tdesktop'
exe=root/'out/Release/Telegram.exe'
if not exe.is_file(): raise SystemExit('Release Telegram.exe missing.')
data=exe.read_bytes()
if data[:2]!=b'MZ': raise SystemExit('Invalid PE signature.')
pe=struct.unpack_from('<I',data,0x3c)[0]
if data[pe:pe+4]!=b'PE\0\0' or struct.unpack_from('<H',data,pe+4)[0]!=0x8664:
    raise SystemExit('Output is not Windows AMD64.')
deps=subprocess.run(['dumpbin','/nologo','/dependents',str(exe)],capture_output=True,text=True,check=True).stdout
if any(x in deps.lower() for x in ('qt5','qt6','vcruntime','msvcp','ucrtbased')):
    raise SystemExit('Unexpected non-system Qt/MSVC runtime DLL dependency; standalone EXE rejected.')
kit=pathlib.Path(os.environ['GITHUB_WORKSPACE'])
out=kit/'artifact';out.mkdir(exist_ok=True)
(out/'Telegram.exe').write_bytes(data)
digest=hashlib.sha256(data).hexdigest()
(out/'Telegram.exe.sha256').write_text(digest+'  Telegram.exe\n',encoding='ascii')
config=json.loads((kit/'kit.json').read_text(encoding='utf-8-sig'))
info={'kit_version':'2.2','source_commit':config['source_commit'],'configuration':'Release',
      'machine':'AMD64','size_bytes':len(data),'sha256':digest,'fallback_seconds':30,
      'kit_commit':os.environ['GITHUB_SHA'],'run_id':os.environ['GITHUB_RUN_ID'],
      'runtime_verified':False,'node_values_in_report':False}
(out/'build-info.json').write_text(json.dumps(info,indent=2)+'\n',encoding='utf-8')
print(f'Telegram.exe: {len(data)/1024**2:.1f} MiB\nSHA-256: {digest}')
if len(data)>150*1024**2: print('::warning::Release EXE exceeds the 150 MiB review threshold. No UPX was used.')
print('Build checks passed. Actual node connection and tdata compatibility still require runtime testing.')
