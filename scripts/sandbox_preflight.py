"""Explicit, non-transactional Sandbox preflight. Report never contains tokens."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scopepay.core import Settings
from scopepay.preflight import check


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True,help='Explicit private env file; no inherited provider configuration')
    parser.add_argument('--oauth',action='store_true',help='Request only a Sandbox OAuth token; requires authorized credentials')
    parser.add_argument('--output',required=True,help='New sanitized JSON evidence file')
    args=parser.parse_args()
    target=Path(args.output)
    if target.exists():
        raise SystemExit('Refusing to overwrite evidence')
    try:
        result=check(Settings.from_env(args.config),oauth=args.oauth)
    except Exception:
        result={'status':'configuration_invalid','error':'Check the explicit configuration file; values are not logged.',
                'orders_created':0,'captures_requested':0,'checkout_verified':False}
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('x',encoding='utf-8') as output:
        json.dump(result,output,ensure_ascii=False,indent=2)
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result['status'] in ('configured_not_authenticated','oauth_authenticated_checkout_unverified') else 2


if __name__=='__main__':
    raise SystemExit(main())
