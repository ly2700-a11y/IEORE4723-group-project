"""Deterministic rules. No LLM output is executed as code or treated as a verdict."""
from collections import defaultdict
from .models import Snapshot, Position, Trade, Rulebook, Security, RATINGS
EPS = 1e-8

def apply_trades(snapshot: Snapshot, trades: list[Trade]) -> Snapshot:
    if len({t.trade_id for t in trades}) != len(trades): raise ValueError('Duplicate trade IDs.')
    values = {p.security_id:p.market_value for p in snapshot.positions}
    # Atomic, same-price batch; no short sales, borrowing, FX, or execution ordering.
    cash = snapshot.cash
    for t in trades:
        values[t.security_id] = values.get(t.security_id,0) + t.delta_value
        cash -= t.delta_value + t.fee
    if any(v < -EPS for v in values.values()): raise ValueError('Batch sells more than available holdings.')
    if cash < -EPS: raise ValueError('Insufficient cash for the net batch plus fees.')
    result = Snapshot(as_of=snapshot.as_of,cash=max(0,cash),positions=[Position(security_id=k,market_value=max(0,v)) for k,v in values.items() if v>EPS])
    if abs(result.nav - (snapshot.nav-sum(t.fee for t in trades))) > max(1e-6,snapshot.nav*1e-12):
        raise ValueError('NAV reconciliation failed.')
    return result

def evaluate(snapshot: Snapshot, book: Rulebook, references: list[Security], max_age=30):
    if len({r.security_id for r in references}) != len(references): raise ValueError('Duplicate reference IDs.')
    refs={r.security_id:r for r in references}; held={p.security_id:p.market_value for p in snapshot.positions if p.market_value>EPS}
    def field(sid,name):
        r=refs.get(sid)
        if r is None or not 0 <= (snapshot.as_of-r.as_of).days <= max_age: return None
        v=getattr(r,name)
        return v if v not in ('','Unknown','-') else None
    findings=[]
    def emit(rule,status,message,actual=None,limit=None,members=None,group=None):
        findings.append(dict(rule_id=rule.id,kind=rule.kind,status=status,message=message,actual=actual,limit=limit,
                             securities=members or [],group=group,evidence=rule.evidence,locator=rule.locator))
    if not book.coverage_confirmed or not book.reviewed_by:
        findings.append(dict(rule_id='COVERAGE',kind='manual',status='REVIEW',message='Document coverage and rulebook review are not confirmed.',actual=None,limit=None,securities=[],group=None,evidence='',locator=''))
    unsupported=[s for s in held if field(s,'asset_type') not in ['Equity','Bond']]
    if unsupported:
        findings.append(dict(rule_id='VALUATION',kind='manual',status='UNKNOWN',message='Missing/stale reference or unsupported asset type; derivative exposure cannot be inferred from market value.',actual=None,limit=None,securities=unsupported,group=None,evidence='',locator=''))
    for rule in book.rules:
        if not rule.evidence_verified or not rule.approved or rule.needs_review or rule.kind=='manual' or rule.basis!='NAV' or rule.timing!='continuous':
            emit(rule,'REVIEW','Requires interpretation or approval; not automatically cleared.');continue
        if rule.effective_from is None:
            emit(rule,'REVIEW','Effective date has not been established.');continue
        if snapshot.as_of<rule.effective_from or (rule.effective_to and snapshot.as_of>rule.effective_to):
            emit(rule,'REVIEW','Rule version does not cover this snapshot date.');continue
        if rule.kind=='cash_floor':
            a=snapshot.cash/snapshot.nav
            emit(rule,'FAIL' if a+EPS<rule.threshold else 'PASS',f'Cash / NAV = {a:.2%}; minimum {rule.threshold:.2%}.',a,rule.threshold)
        elif rule.kind in ['issuer_cap','sector_cap']:
            key='issuer_id' if rule.kind=='issuer_cap' else 'sector';groups=defaultdict(list);missing=[]
            for sid in held:
                v=field(sid,key)
                if v is None: missing.append(sid)
                else: groups[v].append(sid)
            if missing: emit(rule,'UNKNOWN',f'Missing, future-dated or stale {key}: {", ".join(missing)}.',members=missing)
            for group,members in sorted(groups.items()):
                a=sum(held[s] for s in members)/snapshot.nav
                emit(rule,'FAIL' if a>rule.threshold+EPS else ('UNKNOWN' if missing else 'PASS'),
                     f'{group}: {a:.2%} of NAV; maximum {rule.threshold:.2%}.',a,rule.threshold,members,group)
            if not held:emit(rule,'PASS','No non-cash exposure.',0,rule.threshold)
        else:
            failures=[];unknown=[]
            for sid in held:
                if rule.kind=='prohibited_security':
                    if sid in rule.values:failures.append(sid)
                elif rule.kind=='prohibited_type':
                    v=field(sid,'asset_type')
                    if v is None:unknown.append(sid)
                    elif v in rule.values:failures.append(sid)
                elif rule.kind=='esg_exclusion':
                    v=field(sid,'esg_excluded')
                    if v is None:unknown.append(sid)
                    elif v:failures.append(sid)
                elif rule.kind=='min_rating':
                    typ=field(sid,'asset_type')
                    if typ is None:unknown.append(sid)
                    elif typ=='Bond':
                        v=field(sid,'rating')
                        if v not in RATINGS:unknown.append(sid)
                        elif RATINGS.index(v)>RATINGS.index(rule.rating):failures.append(sid)
            if failures:emit(rule,'FAIL','Prohibited or ineligible holdings: '+', '.join(failures),members=failures)
            if unknown:emit(rule,'UNKNOWN','Missing, unrecognized or stale reference data: '+', '.join(unknown),members=unknown)
            if not failures and not unknown:emit(rule,'PASS','No ineligible holdings under this rule.')
    statuses={f['status'] for f in findings}
    overall='FAIL' if 'FAIL' in statuses else 'UNKNOWN' if 'UNKNOWN' in statuses else 'REVIEW' if 'REVIEW' in statuses else 'PASS'
    return dict(overall=overall,nav=snapshot.nav,cash=snapshot.cash,as_of=str(snapshot.as_of),findings=findings,
                unresolved=any(s in statuses for s in ['UNKNOWN','REVIEW']),scope='USD long-only cash/equity/bond snapshot; reviewed rules only')

def remediate(snapshot,book,refs):
    """Sale-to-cash heuristic, NOT an optimal portfolio. Full rulebook is rechecked."""
    current=snapshot; tickets=[]
    for step in range(20):
        result=evaluate(current,book,refs)
        failures=[x for x in result['findings'] if x['status']=='FAIL']
        if not failures:break
        f=failures[0];values={p.security_id:p.market_value for p in current.positions}
        targets=f['securities']
        if f['kind']=='cash_floor':
            targets=list(values);amount=f['limit']*current.nav-current.cash
        elif f['kind'] in ['issuer_cap','sector_cap']: amount=(f['actual']-f['limit'])*current.nav
        else: amount=sum(values.get(s,0) for s in targets)
        total=sum(values.get(s,0) for s in targets)
        if total<=EPS or amount<=EPS: break
        batch=[Trade(trade_id=f'fix-{step}-{i}',security_id=s,delta_value=-min(values[s],amount*values[s]/total)) for i,s in enumerate(targets) if values.get(s,0)>EPS]
        current=apply_trades(current,batch);tickets.extend(batch)
    final=evaluate(current,book,refs)
    return dict(trades=[t.model_dump() for t in tickets],snapshot=current.model_dump(mode='json'),result=final,
                verified=final['overall']=='PASS',assumptions='Same snapshot prices, zero fees, fractional dollar trades, no slippage. Recheck actual executions. Not investment optimization.')
