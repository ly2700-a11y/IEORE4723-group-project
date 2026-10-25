import copy,json,unittest
from datetime import date
from mandate.workflow import ROOT,run,html_report
from mandate.models import Snapshot,Rulebook,Security,Trade
from mandate.engine import evaluate,apply_trades,remediate
from mandate.documents import validate_evidence,extract_text

class ComplianceTests(unittest.TestCase):
    def setUp(self):
        self.bundle=json.loads((ROOT/'data/demo/bundle.json').read_text())
        self.source=(ROOT/'data/demo/mandate.txt').read_bytes()
        self.s=Snapshot.model_validate(self.bundle['snapshot']);self.b=Rulebook.model_validate(self.bundle['rulebook'])
        self.refs=[Security.model_validate(x) for x in self.bundle['references']]
    def trade(self,sid,value,fee=0):return Trade(trade_id='t',security_id=sid,delta_value=value,fee=fee)
    def test_end_to_end(self):
        r=run(self.bundle,self.source,'mandate.txt')
        self.assertEqual([r['before']['overall'],r['after']['overall'],r['remediation']['result']['overall']],['PASS','FAIL','PASS'])
        self.assertTrue(r['remediation']['verified'])
        self.assertEqual(r['after']['cash'],10000)
        failures={x['rule_id'] for x in r['after']['findings'] if x['status']=='FAIL'}
        self.assertEqual(failures,{'R1','R2','R3','R4','R7'})
    def test_issuer_aggregates_share_classes(self):
        s=apply_trades(self.s,[self.trade('ALPHA-B',60000)])
        f=[x for x in evaluate(s,self.b,self.refs)['findings'] if x['rule_id']=='R1' and x['group']=='ALPHA'][0]
        self.assertAlmostEqual(f['actual'],.26);self.assertEqual(f['status'],'FAIL')
    def test_inclusive_boundaries(self):
        s=apply_trades(self.s,[self.trade('ALPHA-A',50000)])
        self.assertEqual(evaluate(s,self.b,self.refs)['overall'],'PASS')
    def test_cash_and_fee_reconcile(self):
        s=apply_trades(self.s,[self.trade('GAMMA',10000,25)])
        self.assertEqual(s.cash,89975);self.assertEqual(s.nav,999975)
    def test_oversell_rejected(self):
        with self.assertRaises(ValueError):apply_trades(self.s,[self.trade('GAMMA',-300000)])
    def test_unfunded_rejected(self):
        with self.assertRaises(ValueError):apply_trades(self.s,[self.trade('GAMMA',100001)])
    def test_duplicate_trade_rejected(self):
        t=self.trade('GAMMA',1)
        with self.assertRaises(ValueError):apply_trades(self.s,[t,t])
    def test_missing_sector_unknown(self):
        self.refs[0].sector=None
        self.assertEqual(evaluate(self.s,self.b,self.refs)['overall'],'UNKNOWN')
    def test_missing_esg_unknown(self):
        self.refs[0].esg_excluded=None
        self.assertEqual(evaluate(self.s,self.b,self.refs)['overall'],'UNKNOWN')
    def test_future_reference_unknown(self):
        self.refs[0].as_of=date(2027,1,1)
        self.assertEqual(evaluate(self.s,self.b,self.refs)['overall'],'UNKNOWN')
    def test_stale_reference_unknown(self):
        self.refs[0].as_of=date(2025,1,1)
        self.assertEqual(evaluate(self.s,self.b,self.refs)['overall'],'UNKNOWN')
    def test_duplicate_reference_rejected(self):
        with self.assertRaises(ValueError):evaluate(self.s,self.b,self.refs+[self.refs[0]])
    def test_low_rating_fail(self):
        s=apply_trades(self.s,[self.trade('JUNK',10000)])
        self.assertIn('R6',[f['rule_id'] for f in evaluate(s,self.b,self.refs)['findings'] if f['status']=='FAIL'])
    def test_unrated_bond_unknown(self):
        self.refs[5].rating=None
        self.assertEqual(evaluate(self.s,self.b,self.refs)['overall'],'UNKNOWN')
    def test_unsupported_asset_not_cleared(self):
        self.refs[0].asset_type='ETF'
        self.assertEqual(evaluate(self.s,self.b,self.refs)['overall'],'UNKNOWN')
    def test_purchase_rule_not_cleared(self):
        self.b.rules[0].timing='purchase_only'
        self.assertEqual(evaluate(self.s,self.b,self.refs)['overall'],'REVIEW')
    def test_unapproved_not_cleared(self):
        self.b.rules[0].approved=False
        self.assertEqual(evaluate(self.s,self.b,self.refs)['overall'],'REVIEW')
    def test_coverage_not_cleared(self):
        self.b.coverage_confirmed=False
        self.assertEqual(evaluate(self.s,self.b,self.refs)['overall'],'REVIEW')
    def test_rule_date_not_cleared(self):
        self.b.rules[0].effective_from=date(2027,1,1)
        self.assertEqual(evaluate(self.s,self.b,self.refs)['overall'],'REVIEW')
    def test_unknown_cannot_be_fixed_away(self):
        self.refs[0].esg_excluded=None
        self.assertFalse(remediate(self.s,self.b,self.refs)['verified'])
    def test_forged_evidence_rejected(self):
        self.b.rules[0].evidence='invented quotation'
        with self.assertRaises(ValueError):validate_evidence(self.b,self.source,self.source.decode())
    def test_changed_document_rejected(self):
        with self.assertRaises(ValueError):run(self.bundle,self.source+b'changed','mandate.txt')
    def test_invalid_threshold_rejected(self):
        self.bundle['rulebook']['rules'][0]['threshold']=25
        with self.assertRaises(ValueError):run(self.bundle,self.source,'mandate.txt')
    def test_nonfinite_amount_rejected(self):
        with self.assertRaises(ValueError):self.trade('A',float('nan'))
    def test_html_escapes_input(self):
        r=run(self.bundle,self.source,'mandate.txt');r['source_name']='<script>alert(1)</script>'
        self.assertNotIn('<script>',html_report(r));self.assertIn('&lt;script&gt;',html_report(r))
    def test_all_cash_portfolio(self):
        s=Snapshot(as_of=self.s.as_of,cash=1000000,positions=[])
        self.assertEqual(evaluate(s,self.b,[])['overall'],'PASS')

if __name__=='__main__':unittest.main()
