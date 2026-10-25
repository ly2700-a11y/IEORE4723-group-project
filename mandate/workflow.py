import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from .models import Rulebook, Snapshot, Security, Trade
from .documents import extract_text, validate_evidence, digest
from .engine import evaluate, apply_trades, remediate

ROOT=Path(__file__).resolve().parents[1]

def add_input_issues(result,issues):
    for issue in issues:
        result['findings'].append(dict(rule_id='INPUT_COVERAGE',kind='manual',status='UNKNOWN',message=issue,actual=None,limit=None,securities=[],group=None,evidence='',locator='Holdings import'))
    if issues:
        result['unresolved']=True
        if result['overall']!='FAIL':result['overall']='UNKNOWN'
    return result

def run(bundle,source_data,source_name):
    book=Rulebook.model_validate(bundle['rulebook']);snapshot=Snapshot.model_validate(bundle['snapshot'])
    refs=[Security.model_validate(x) for x in bundle['references']]
    trades=[Trade.model_validate(x) for x in bundle['trades']]
    validate_evidence(book,source_data,extract_text(source_data,source_name))
    before=evaluate(snapshot,book,refs)
    after_snapshot=apply_trades(snapshot,trades)
    after=evaluate(after_snapshot,book,refs)
    fix=remediate(after_snapshot,book,refs)
    for result in (before,after,fix['result']):add_input_issues(result,bundle.get('input_issues',[]))
    fix['verified']=fix['result']['overall']=='PASS' 
    return dict(created_at=datetime.now(timezone.utc).isoformat(),source_name=source_name,
                source_sha256=digest(source_data),input_sha256=digest(json.dumps(bundle,sort_keys=True).encode()),
                source_type=book.source_type,inputs=bundle,before=before,after=after,
                after_snapshot=after_snapshot.model_dump(mode='json'),remediation=fix,
                execution_assumptions='Atomic batch at fixed snapshot prices; signed USD market values; no shorting/borrowing/FX. Post-trade is simulated, not a broker confirmation.',
                status_legend={'PASS':'Passed under the supplied rules, data and assumptions','FAIL':'Confirmed breach','UNKNOWN':'Insufficient data','REVIEW':'Manual interpretation or approval required'})

def html_report(report):
    def table(result):
        rows=''.join('<tr>'+''.join('<td>'+escape(str(f.get(k,'')))+'</td>' for k in ['rule_id','status','message','evidence','locator'])+'</tr>' for f in result['findings'])
        return f'<p>Status: <b>{escape(result["overall"])}</b> | NAV: ${result["nav"]:,.2f} | Cash: ${result["cash"]:,.2f}</p><table><tr><th>Rule</th><th>Status</th><th>Result</th><th>Source evidence</th><th>Location</th></tr>{rows}</table>'
    fix=report['remediation']
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><title>Investment Mandate Compliance Report</title>
<style>body{font:15px system-ui;max-width:1150px;margin:40px auto;color:#18333d;padding:20px}table{border-collapse:collapse;width:100%;font-size:13px}td,th{border:1px solid #cad8dc;padding:9px;text-align:left;vertical-align:top}th{background:#e9f2f3}pre{white-space:pre-wrap;background:#f3f5f6;padding:16px}h2{margin-top:35px}code{overflow-wrap:anywhere}@media print{body{margin:0}tr{break-inside:avoid}}</style>'''+f'''<h1>Investment Mandate Compliance Report</h1><p>Generated: {escape(report['created_at'])}</p>
<p>Data type: {escape(report['source_type'])}. Synthetic examples do not represent any real fund mandate or holdings.</p>
<p>Source: {escape(report['source_name'])}<br>Document SHA256: <code>{report['source_sha256']}</code><br>Input SHA256: <code>{report['input_sha256']}</code></p>
<p>PASS: passed under supplied rules and data; FAIL: breach; UNKNOWN: insufficient data; REVIEW: manual review. A PASS is not a comprehensive legal compliance certification.</p>
<h2>1. Before trades</h2>{table(report['before'])}<h2>2. Proposed trades</h2><pre>{escape(json.dumps(report['inputs']['trades'],ensure_ascii=False,indent=2))}</pre>
<h2>3. After simulated trades</h2>{table(report['after'])}
<h2>4. Remediation and verification</h2><p>All checks passed: {'Yes' if fix['verified'] else 'No'}</p><pre>{escape(json.dumps(fix['trades'],ensure_ascii=False,indent=2))}</pre>{table(fix['result'])}
<p>Remediation is a sales-to-cash heuristic, not an optimal portfolio. It assumes fixed snapshot prices, zero fees and fractional amounts. Recheck actual executions. User-entered fees are included in the original proposed trade batch.</p>
<p>Scope: USD long-only cash, equities and ordinary bonds. Derivative exposure, multiple currencies, purchase-only conditions and complex exceptions cannot be cleared automatically.</p></html>'''

def save_report(report):
    folder=ROOT/'outputs'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');folder.mkdir(parents=True)
    (folder/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (folder/'report.html').write_text(html_report(report),encoding='utf-8')
    (folder/'proposed_remediation.json').write_text(json.dumps(report['remediation']['trades'],indent=2))
    return folder
