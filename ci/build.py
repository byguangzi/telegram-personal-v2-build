"""Run upstream configuration and MSBuild while redacting build credentials."""
import base64, ctypes, json, os, pathlib, re, subprocess, sys, threading

def report_memory():
    """Only report resource counters, never the process environment or arguments."""
    if sys.platform != 'win32':
        return
    class MemoryStatus(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
            (name, ctypes.c_ulonglong) for name in (
                'physical', 'available', 'commit_limit', 'commit_available',
                'virtual', 'virtual_available', 'extended')]
    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        gib = 1024 ** 3
        print('Memory: physical available %.2f / %.2f GiB; '
              'commit available %.2f / %.2f GiB' % (
                  status.available/gib, status.physical/gib,
                  status.commit_available/gib, status.commit_limit/gib), flush=True)

# MSBuild project parallelism and CL source-file parallelism are separate.
# _CL_ is appended after generated project options, overriding an upstream /MP.
os.environ['_CL_'] = (os.environ.get('_CL_', '') + ' /MP1').strip()
os.environ['CMAKE_BUILD_PARALLEL_LEVEL'] = '1'
print('Build resource policy: one MSBuild project, /MP1, x64 compiler host.', flush=True)

root = pathlib.Path(os.environ['TBUILD']) / 'tdesktop'
kit = pathlib.Path(os.environ['GITHUB_WORKSPACE'])
names = ('TDESKTOP_API_ID','TDESKTOP_API_HASH','PRECONFIGURED_PROXY_HOST',
         'PRECONFIGURED_PROXY_PORT','PRECONFIGURED_PROXY_SECRET')
values = [os.environ.get(n, '') for n in names]
api_id, api_hash = values[:2]
if not re.fullmatch(r'[1-9][0-9]{0,9}',api_id) or int(api_id)>2147483647:
    raise SystemExit('TDESKTOP_API_ID missing or invalid.')
if not re.fullmatch(r'[0-9a-fA-F]{32}',api_hash):
    raise SystemExit('TDESKTOP_API_HASH missing or invalid.')
redactions = set(filter(None, values))
for value in values:
    if value: redactions.add(base64.b64encode(value.encode()).decode())
# The generated header stores a canonical hexadecimal secret.
from generate_proxy import normalize_mtproto_secret
canonical = normalize_mtproto_secret(values[4])
redactions.update((canonical,base64.b64encode(canonical.encode()).decode()))
redactions = sorted(redactions,key=len,reverse=True)
def redact(text):
    for value in redactions: text=text.replace(value,'[REDACTED]')
    return text
def run(args,cwd):
    report_memory()
    process=subprocess.Popen(args,cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                             encoding='utf-8',errors='replace')
    stopped = threading.Event()
    def monitor():
        while not stopped.wait(60): report_memory()
    watcher = threading.Thread(target=monitor, daemon=True)
    watcher.start()
    try:
        for line in process.stdout: print(redact(line),end='',flush=True)
        result = process.wait()
    finally:
        stopped.set()
        watcher.join()
        report_memory()
    if result: raise SystemExit('Build command failed; actual redacted output is above.')
run([sys.executable,'configure.py','x64',
     '-D',f'TDESKTOP_API_ID={api_id}','-D',f'TDESKTOP_API_HASH={api_hash}',
     '-D','CMAKE_CONFIGURATION_TYPES=Release',
     '-D','CMAKE_MSVC_DEBUG_INFORMATION_FORMAT=',
     '-D','DESKTOP_APP_DISABLE_AUTOUPDATE=ON',
     '-D','DESKTOP_APP_DISABLE_CRASH_REPORTS=ON'],root/'Telegram')
cache=(root/'out/CMakeCache.txt').read_text(encoding='utf-8',errors='replace')
def cache_value(name):
    m=re.search(r'^'+re.escape(name)+r':[^=]*=(.*)$',cache,re.M)
    return m.group(1).strip() if m else None
for name,value in (('CMAKE_CONFIGURATION_TYPES','Release'),('DESKTOP_APP_DISABLE_AUTOUPDATE','ON'),('DESKTOP_APP_DISABLE_CRASH_REPORTS','ON')):
    if cache_value(name)!=value: raise SystemExit('Unexpected build setting: '+name)
run(['cmake','--build',str(root/'out'),'--config','Release','--target','Telegram',
     '--parallel','1','--','/p:PreferredToolArchitecture=x64',
     '/p:MultiProcessorCompilation=false','/nodeReuse:false'],root)
print('Release target completed; configuration checks passed.')
