import json,unittest
from unittest.mock import patch,MagicMock
from types import SimpleNamespace
from mandate.workflow import ROOT,run
from mandate.imports import import_holdings,combine_documents
from mandate.models import Rulebook
from mandate.llm import extract_documents,explain_and_propose

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.bundle=json.loads((ROOT/'data/demo/bundle.json').read_text());self.source=(ROOT/'data/demo/mandate.txt').read_bytes()
    def response(self,obj):
        return SimpleNamespace(content=[SimpleNamespace(type='text',text=json.dumps(obj))],stop_reason='end_turn',usage=SimpleNamespace(model_dump=lambda:{}))
    def test_public_holdings_preserve_zero_future(self):
        got=import_holdings((ROOT/'data/public/esgu_holdings.csv').read_bytes())
        self.assertIn({'security_id':'ESZ6','market_value':0.0},got['snapshot']['positions'])
        self.assertTrue(any('ESZ6' in i for i in got['input_issues']))
        self.assertAlmostEqual(got['snapshot']['cash'],7015387.64)
        self.assertTrue(all(r['issuer_id'] is None for r in got['references']))
    def test_input_issues_survive_all_cash_remediation(self):
        self.bundle['input_issues']=['Zero market value derivative with exposure']
        r=run(self.bundle,self.source,'mandate.txt')
        self.assertEqual(r['before']['overall'],'UNKNOWN')
        self.assertEqual(r['after']['overall'],'FAIL')
        self.assertFalse(r['remediation']['verified'])
    def test_csv_missing_fields_rejected(self):
        with self.assertRaises(ValueError):import_holdings(b'ticker,value\nA,1')
    def test_csv_currency_rejected(self):
        with self.assertRaises(ValueError):import_holdings(b'security_id,market_value,asset_type,as_of,currency\nA,1,Equity,2026-10-23,EUR\n')
    def test_documents_combined_with_provenance(self):
        data,m=combine_documents([('one.txt',self.source),('two.txt',self.source)])
        self.assertEqual(len(m),2);self.assertIn(b'Document 2: two.txt',data)
    @patch('anthropic.Anthropic')
    def test_extraction_never_auto_approves(self,client):
        client.return_value.messages.create.return_value=self.response({'rules':[self.bundle['rulebook']['rules'][0]]})
        book,audit=extract_documents(self.source,'Synthetic','fake','mock')
        self.assertFalse(book.rules[0].approved);self.assertTrue(book.rules[0].needs_review)
        self.assertFalse(book.coverage_confirmed);self.assertEqual(audit['chunks'],1)
    @patch('anthropic.Anthropic')
    def test_long_documents_all_chunks_read(self,client):
        rule=self.bundle['rulebook']['rules'][0];data=(rule['evidence']+'\n').encode()*2000
        # No rules still must consume every chunk, then reject empty coverage.
        client.return_value.messages.create.return_value=self.response({'rules':[]})
        with self.assertRaises(ValueError):extract_documents(data,'Synthetic','fake','mock')
        length=len(data.decode());expected=1+(max(0,length-30000)+28499)//28500
        self.assertEqual(client.return_value.messages.create.call_count,expected)
    @patch('anthropic.Anthropic')
    def test_model_remediation_rechecked(self,client):
        report=run(self.bundle,self.source,'mandate.txt')
        client.return_value.messages.create.return_value=self.response(dict(explanation='test',rationale='test',trades=report['remediation']['trades']))
        memo=explain_and_propose(report,'fake','mock');self.assertTrue(memo['verified'])
    @patch('anthropic.Anthropic')
    def test_bad_model_proposal_not_pass(self,client):
        report=run(self.bundle,self.source,'mandate.txt')
        client.return_value.messages.create.return_value=self.response(dict(explanation='Everything fine',rationale='none',trades=[]))
        memo=explain_and_propose(report,'fake','mock');self.assertFalse(memo['verified']);self.assertEqual(memo['result']['overall'],'FAIL')
    @patch('anthropic.Anthropic')
    def test_model_oversell_rejected(self,client):
        report=run(self.bundle,self.source,'mandate.txt')
        client.return_value.messages.create.return_value=self.response(dict(explanation='test',rationale='test',trades=[dict(trade_id='x',security_id='ALPHA-A',delta_value=-1e9)]))
        with self.assertRaises(ValueError):explain_and_propose(report,'fake','mock')

    @patch('anthropic.Anthropic')
    def test_failed_chunk_diagnostic_and_resume(self,client):
        rule=self.bundle['rulebook']['rules'][0]
        data=(rule['evidence']+'\n'+'x'*31000).encode()
        client.return_value.messages.create.side_effect=[self.response({'rules':[rule]}),self.response({'not_rules':[]}),self.response({'rules':[]})]
        state={}
        with self.assertRaisesRegex(ValueError,'Chunk 2/2 failed'):
            extract_documents(data,'Synthetic','fake','mock',state=state)
        self.assertEqual(len(state['completed']),1)
        self.assertIn('rules array',state['last_failure']['reason'])
        book,audit=extract_documents(data,'Synthetic','fake','mock',state=state)
        self.assertEqual(client.return_value.messages.create.call_count,3)
        self.assertEqual(len(book.rules),1)
        self.assertNotIn('last_failure',state)

    @patch('anthropic.Anthropic')
    def test_unmatched_quote_quarantined_and_not_cleared(self,client):
        from mandate.documents import validate_evidence
        from mandate.engine import evaluate
        from mandate.models import Snapshot,Security
        bad=dict(self.bundle['rulebook']['rules'][0],evidence='Unverifiable invented quote')
        client.return_value.messages.create.return_value=self.response({'rules':[bad]})
        book,audit=extract_documents(self.source,'Synthetic','fake','mock')
        rule=book.rules[0]
        self.assertFalse(rule.evidence_verified)
        validate_evidence(book,self.source,self.source.decode())
        book.coverage_confirmed=True;book.reviewed_by='tester'
        rule.needs_review=False;rule.approved=True
        result=evaluate(Snapshot.model_validate(self.bundle['snapshot']),book,[Security.model_validate(x) for x in self.bundle['references']])
        self.assertEqual(result['overall'],'REVIEW')
        with self.assertRaises(ValueError):validate_evidence(book,self.source,self.source.decode())
