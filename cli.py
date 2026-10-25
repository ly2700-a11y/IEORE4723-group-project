"""Run from project: python cli.py demo | python cli.py check --bundle ... --document ..."""
import argparse,json
from pathlib import Path
from mandate.workflow import ROOT,run,save_report

def main():
    p=argparse.ArgumentParser(description='Investment mandate compliance monitor')
    p.add_argument('command',choices=['demo','check']);p.add_argument('--bundle');p.add_argument('--document')
    a=p.parse_args()
    if a.command=='demo': b=ROOT/'data/demo/bundle.json';d=ROOT/'data/demo/mandate.txt'
    else:
        if not a.bundle or not a.document:p.error('check requires --bundle and --document')
        b=Path(a.bundle);d=Path(a.document)
    report=run(json.loads(b.read_text()),d.read_bytes(),d.name);out=save_report(report)
    print(f"Before: {report['before']['overall']} | After: {report['after']['overall']} | Remediation: {report['remediation']['result']['overall']}")
    print(f'Report: {out / "report.html"}')
if __name__=='__main__':main()
