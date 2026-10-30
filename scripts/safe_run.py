"""Run project commands without inherited provider credentials. No cleanup."""
import os
import subprocess
import sys


def safe_environment():
    allowed = {'PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'TEMP', 'TMP',
               'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'PROGRAMFILES', 'PROGRAMDATA',
               'HOMEDRIVE', 'HOMEPATH', 'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE'}
    env = {k: v for k, v in os.environ.items() if k.upper() in allowed}
    env.update(PYTHONIOENCODING='utf-8', PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
    return env


if __name__ == '__main__':
    args = sys.argv[1:]
    if not args:
        raise SystemExit('Usage: safe_run.py command [args...]')
    raise SystemExit(subprocess.call(args, env=safe_environment()))
