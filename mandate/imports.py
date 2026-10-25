"""Loss-aware holdings import. Missing reference data is never guessed."""
import csv,io,json
from datetime import datetime
from .models import Snapshot,Security
from .documents import digest,extract_text

def combine_documents(files):
    parts=[];manifest=[]
    for i,(name,data) in enumerate(files,1):
        text=extract_text(data,name)
        marker=f'Document {i}: {name} | SHA256 {digest(data)}'
        parts.append(marker+'\n'+text)
        manifest.append(dict(name=name,sha256=digest(data),characters=len(text)))
    combined='\n\n'.join(parts).encode('utf-8')
    return combined,manifest

def number(value):
    v=float(str(value).replace(',',''))
    import math
    if not math.isfinite(v):raise ValueError('Amounts must be finite numbers.')
    return v

def import_holdings(data):
    text=data.decode('utf-8-sig');lines=text.splitlines()
    start=next((i for i,l in enumerate(lines) if l.startswith('Ticker,')),None)
    positions=[];refs=[];issues=[];cash=0
    if start is not None:
        header=list(csv.reader(lines[:start]));dt=next((r[1] for r in header if r and r[0]=='Fund Holdings as of'),None)
        if not dt:raise ValueError('The holdings file has no valuation date.')
        asof=datetime.strptime(dt,'%b %d, %Y').date().isoformat()
        rows=list(csv.DictReader(io.StringIO('\n'.join(lines[start:]))))
        for row in rows:
            sid=row.get('Ticker','').strip()
            if not sid:continue
            value=number(row['Market Value']);typ=row['Asset Class'];currency=row['Currency']
            if value<0:raise ValueError(f'{sid} has negative market value, which the long-only engine does not support.')
            if currency!='USD':raise ValueError(f'{sid} is not valued in USD; provide explicitly converted USD values first.')
            if typ=='Cash':cash+=value;continue
            typ={'Futures':'Future','Fixed Income':'Bond'}.get(typ,typ)
            positions.append(dict(security_id=sid,market_value=value))
            refs.append(dict(security_id=sid,issuer_id=None,sector=row.get('Sector'),asset_type=typ,rating=None,esg_excluded=None,as_of=asof,source='Uploaded official holdings CSV; issuer/rating/ESG not supplied'))
            if typ not in ('Equity','Bond'):
                issues.append(f'{sid}: {typ}; market value {value:,.2f}; notional amount {row.get("Notional Value","unknown")}; exposure and cash treatment require manual review.')
    else:
        rows=list(csv.DictReader(io.StringIO(text)))
        if not rows:raise ValueError('The holdings CSV is empty.')
        required={'security_id','market_value','asset_type','as_of','currency'}
        if not required<=set(rows[0]):raise ValueError('Upload an original iShares holdings CSV or a standard CSV containing security_id,market_value,asset_type,as_of,currency.')
        dates={r['as_of'] for r in rows}
        if len(dates)!=1:raise ValueError('All rows must use the same valuation date.')
        asof=dates.pop()
        for r in rows:
            if r['currency']!='USD':raise ValueError('Only USD valuations are supported.')
            value=number(r['market_value']);typ=r['asset_type'];sid=r['security_id']
            if value<0:raise ValueError('Negative market values are unsupported.')
            if typ=='Cash':cash+=value;continue
            esg=r.get('esg_excluded','').strip().lower()
            if esg not in ('','true','false'):raise ValueError('esg_excluded must be true, false or blank.')
            positions.append(dict(security_id=sid,market_value=value))
            refs.append(dict(security_id=sid,issuer_id=r.get('issuer_id') or None,sector=r.get('sector') or None,asset_type=typ,rating=r.get('rating') or None,esg_excluded=None if not esg else esg=='true',as_of=asof,source=r.get('source') or 'User-uploaded holdings/reference CSV'))
            if typ not in ('Equity','Bond'):issues.append(f'{sid}: Unsupported asset type {typ}, including zero-market-value exposure; manual review required.')
    snapshot=Snapshot(as_of=asof,cash=cash,positions=positions)
    for r in refs:Security.model_validate(r)
    return dict(snapshot=snapshot.model_dump(mode='json'),references=refs,input_issues=issues,holdings_sha256=digest(data))
