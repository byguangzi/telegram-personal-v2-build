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

from build_tuning import (available_memory, select_workers, configure_workers,
                          resource_error, build_command)
physical, commit = available_memory()
workers = select_workers(os.environ.get('BUILD_MODE', 'auto'), os.cpu_count(), physical, commit)
configure_workers(workers)
print('Build scheduling: one MSBuild project, /MP%d; feature/compiler optimization flags unchanged.' % workers, flush=True)

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
def run(args,cwd,allow_failure=False):
    report_memory()
    process=subprocess.Popen(args,cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                             encoding='utf-8',errors='replace')
    stopped = threading.Event()
    def monitor():
        while not stopped.wait(60): report_memory()
    watcher = threading.Thread(target=monitor, daemon=True)
    watcher.start()
    resource_failure = False
    try:
        for line in process.stdout:
            resource_failure = resource_failure or resource_error(line)
            print(redact(line),end='',flush=True)
        result = process.wait()
    finally:
        stopped.set()
        watcher.join()
        report_memory()
    if result and not allow_failure: raise SystemExit('Build command failed; actual redacted output is above.')
    return result, resource_failure
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
result, exhausted = run(build_command(root, workers), root, allow_failure=True)
if result and exhausted and workers > 1:
    print('Explicit MSVC memory/resource failure: retrying once with original serial scheduling.', flush=True)
    configure_workers(1)
    result, _ = run(build_command(root, 1), root, allow_failure=True)
if result:
    raise SystemExit('Release build failed; no artifact is accepted. Actual redacted output is above.')
print('Release target completed; configuration checks passed.')
