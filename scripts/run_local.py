"""Run the local workspace with one explicit configuration, without reading .env."""
import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scopepay.app import create_app
from scopepay.core import Settings


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True)
    args=parser.parse_args()
    try:
        settings=Settings.from_env(args.config)
    except Exception:
        raise SystemExit('Invalid explicit configuration; no values logged.') from None
    origin=urlparse(settings.app_url)
    import uvicorn
    uvicorn.run(create_app(settings),host='127.0.0.1',port=origin.port or 80,
                log_level='warning',access_log=False)


if __name__=='__main__':
    main()
