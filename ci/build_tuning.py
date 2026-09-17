"""Scheduling only: no source, feature, code-generation, or linker flag changes."""
import ctypes
import os
import re
import sys


def available_memory():
    if sys.platform != 'win32':
        return 0, 0
    class Status(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
            (name, ctypes.c_ulonglong) for name in (
                'physical', 'available', 'commit_limit', 'commit_available',
                'virtual', 'virtual_available', 'extended')]
    value = Status()
    value.length = ctypes.sizeof(value)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):
        return 0, 0
    return value.available, value.commit_available


def select_workers(mode, cpus, physical_available, commit_available):
    if mode not in ('auto', 'safe'):
        raise ValueError('Unsupported build mode; expected auto or safe.')
    gib = 1024 ** 3
    if (mode == 'auto' and (cpus or 1) >= 2
            and physical_available >= 10 * gib and commit_available >= 12 * gib):
        return 2
    return 1


def configure_workers(workers):
    if workers not in (1, 2):
        raise ValueError('Only one or two compiler processes are supported.')
    # _CL_ is appended by MSVC after command-line options. Replace only /MP.
    previous = re.sub(r'(?i)(?<!\S)/MP\d*(?!\S)', '', os.environ.get('_CL_', ''))
    os.environ['_CL_'] = (previous.strip() + ' /MP' + str(workers)).strip()
    os.environ['CMAKE_BUILD_PARALLEL_LEVEL'] = '1'


def resource_error(line):
    # Retry only explicit MSVC resource exhaustion, never ordinary source errors.
    return bool(re.search(r'\b(?:C1060|C1076|C3859|LNK1102)\b', line))


def build_command(root, workers):
    return ['cmake', '--build', str(root / 'out'), '--config', 'Release',
            '--target', 'Telegram', '--parallel', '1', '--',
            '/p:PreferredToolArchitecture=x64',
            '/p:MultiProcessorCompilation=' + ('true' if workers > 1 else 'false'),
            '/nodeReuse:false']
