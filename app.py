import copy,io,json,os
import pandas as pd
import streamlit as st
from mandate.workflow import ROOT,run,save_report,html_report
from mandate.documents import digest,validate_evidence
from mandate.imports import combine_documents,import_holdings
from mandate.models import Rulebook,Security
from mandate.llm import extract_documents,explain_and_propose

st.set_page_config(page_title='Mandate Monitor · Mandate Compliance',page_icon='⚖️',layout='wide')
st.markdown('<style>.block-container{max-width:1350px;padding-top:2rem}div[data-testid="stMetric"]{background:#eef5f5;padding:18px;border-radius:12px}h1{color:#153e48}</style>',unsafe_allow_html=True)
st.title('Investment Mandate Compliance Monitor')
st.caption('Topic 5 · Documents → Rules → Holdings and trades → Explanation and remediation')
with st.sidebar:
    mode=st.radio('Workflow',['Real fund workflow','Teaching demo'],key='mode_v2')
    st.subheader('Claude')
    key=st.text_input('Anthropic API key',type='password',value=os.getenv('ANTHROPIC_API_KEY',''))
    model=st.text_input('Available model ID',value=os.getenv('ANTHROPIC_MODEL',''),placeholder='Enter a model ID supported by your account')
    st.caption('Documents or reports are sent to Claude only when you click an API button. API usage may incur charges. Keys are never included in reports.')
    st.caption('Trades are simulated at fixed USD valuations and are never sent to a broker.')
tabs=st.tabs(['① Documents and rules','② Holdings and trade checks','③ Explanation and remediation','④ Public resources'])
bundle=None;source=None;source_name='mandate_package.txt';report=None

@st.cache_data(show_spinner=False)
def read_package(files):return combine_documents(files)

def show_result(result):
    st.dataframe(pd.DataFrame(result['findings'])[['rule_id','status','message','evidence','locator']],hide_index=True,width='stretch')

with tabs[0]:
    st.subheader('Upload fund documents, extract and review constraints')
    if mode=='Teaching demo':
        bundle=json.loads((ROOT/'data/demo/bundle.json').read_text())
        source=(ROOT/'data/demo/mandate.txt').read_bytes();source_name='mandate.txt'
        st.info('The demo includes a synthetic mandate, reviewed rules and holdings. No API is required. Follow the tabs in order.')
        st.dataframe(pd.DataFrame(bundle['rulebook']['rules']),hide_index=True,width='stretch')
        with st.expander('Mandate source text'):st.text(source.decode())
    else:
        target=st.text_input('Target fund name / ticker','iShares ESG Aware MSCI USA ETF (ESGU)')
        files=st.file_uploader('Upload the prospectus, SAI and applicable supplements together',type=['pdf','txt','md'],accept_multiple_files=True,key='docs_v2')
        use_public=st.checkbox('Use the downloaded ESGU prospectus and SAI',value=False)
        pairs=[(f.name,f.getvalue()) for f in files] if files else []
        if use_public and not pairs:pairs=[(n,(ROOT/'data/public'/n).read_bytes()) for n in ['esgu_prospectus.pdf','esgu_sai.pdf']]
        if use_public and files:st.caption('Uploaded files take priority; local public files have not been added.')
        if pairs:
            try:
                source,manifest=read_package(pairs)
                context=digest(source+target.encode())
                st.dataframe(pd.DataFrame(manifest)[['name','characters']],hide_index=True,width='stretch')
                chunks=max(1,1+(max(0,len(source.decode())-30000)+28499)//28500)
                st.caption(f'All document text will be read in approximately {chunks} overlapping chunks, with one API call per chunk. Long SAIs are not truncated. Full-text coverage does not guarantee semantic completeness; exceptions, amendments and fund applicability require review.')
                if st.button('Extract constraints from all documents with Claude',disabled=not(key and model and target.strip())):
                    st.session_state.pop('reviewed_v2',None);st.session_state.pop('candidate_v2',None)
                    progress=st.progress(0,text='Preparing extraction')
                    try:
                        state=st.session_state.setdefault('extraction_state',{})
                        book,audit=extract_documents(source,target,key,model,lambda i,n:progress.progress(i/n,text=f'Reading chunk {i+1}/{n}'),state=state)
                        progress.progress(1,text='Extraction complete; review required')
                        st.session_state.candidate_v2=dict(context=context,book=book.model_dump(mode='json'),audit=audit)
                    except Exception as e:
                        progress.empty()
                        message=str(e) if isinstance(e,ValueError) else f'{type(e).__name__}: Check your API configuration or network.'
                        st.error('Extraction incomplete: '+message)
                diagnostic=st.session_state.get('extraction_state',{})
                if diagnostic.get('identity')==digest(source+target.encode()+model.encode()) and diagnostic.get('last_failure'):
                    with st.expander('Failure diagnostics',expanded=True):
                        failure=diagnostic['last_failure']
                        st.write(f"Chunk {failure['chunk']}/{failure['total_chunks']}: {failure['reason']}")
                        st.caption('Successful chunks are retained in this session. Do not reload or close the page. Retry extraction to resume without requesting successful chunks again.')
                        st.download_button('Download failure diagnostics (no API key)',json.dumps(failure,ensure_ascii=False,indent=2),'extraction_failure.json')
                candidate=st.session_state.get('candidate_v2')
                if candidate and candidate['context']==context:
                    st.subheader('Candidate constraints and rule-by-rule review')
                    st.write('Review quotations, fund applicability, limits, denominators, timing, exceptions and effective dates. Retain constraints that cannot be checked automatically; do not remove them to obtain a PASS.')
                    unresolved=sum(not r.get('evidence_verified',True) for r in candidate['book']['rules'])
                    if unresolved:st.warning(f'{unresolved} candidate quotations are unverified and quarantined for review. Correct evidence to a verbatim source quotation before approval; unresolved candidates cannot pass automatically.')
                    rows=copy.deepcopy(candidate['book']['rules'])
                    for row in rows:row['values']=', '.join(row.get('values',[]))
                    grid=st.data_editor(pd.DataFrame(rows),hide_index=True,width='stretch',key='review_'+context,
                        disabled=['id','locator','evidence_verified'],column_config={'approved':st.column_config.CheckboxColumn('Approved'),'needs_review':st.column_config.CheckboxColumn('Requires manual review'),'threshold':st.column_config.NumberColumn('Threshold (0–1)',min_value=0,max_value=1)})
                    reviewer=st.text_input('Reviewer',key='reviewer_'+context)
                    complete=st.checkbox('I reviewed document scope, amendments and omissions, and retained uncertain constraints for manual review',key='coverage_'+context)
                    if st.button('Confirm rules and continue to step 2',disabled=not(reviewer.strip() and complete)):
                        try:
                            rows=json.loads(grid.to_json(orient='records',date_format='iso'))
                            for row in rows:row['values']=[v.strip() for v in (row.get('values') or '').split(',') if v.strip()]
                            obj=copy.deepcopy(candidate['book']);obj.update(rules=rows,reviewed_by=reviewer.strip(),coverage_confirmed=True)
                            for rule in obj['rules']:
                                rule['evidence_verified']=' '.join(rule['evidence'].split()) in ' '.join(source.decode().split())
                            book=Rulebook.model_validate(obj);validate_evidence(book,source,source.decode())
                            st.session_state.reviewed_v2=dict(context=context,book=book.model_dump(mode='json'),manifest=manifest)
                            st.success('Rules are available in step 2. Unapproved or unsupported constraints remain marked REVIEW.')
                        except Exception as e:st.error(f'Rule validation failed: {e}')
                    st.download_button('Download extraction audit',json.dumps(candidate['audit'],ensure_ascii=False,indent=2),'extraction_audit.json')
                approved=st.session_state.get('reviewed_v2')
                if approved and approved['context']==context:
                    bundle=dict(rulebook=approved['book'],documents=manifest,trades=[])
                    st.success('Step 1 is confirmed. Upload holdings next. Changing documents or the target fund requires extraction and review again.')
            except Exception as e:st.error(f'Unable to read documents: {e}')
        else:st.info('Upload the PDFs or select the downloaded ESGU documents.')

with tabs[1]:
    st.subheader('Import holdings and check proposed trades')
    st.write('Check current holdings, then simulate proposed trades and assess the resulting portfolio. Pre-trade clearance depends on whether the simulated portfolio satisfies the rules.')
    if bundle is None:st.info('Extract and confirm rules in step 1 first, or select Teaching demo in the sidebar.')
    else:
        if mode=='Real fund workflow':
            upload=st.file_uploader('Upload holdings CSV (original iShares files supported)',type=['csv'],key='holdings_v2')
            local=st.checkbox('Use downloaded ESGU holdings',key='local_holdings')
            template='security_id,market_value,asset_type,as_of,currency,issuer_id,sector,rating,esg_excluded,source\nUSD,10000,Cash,2026-10-23,USD,,,,,User\nEXAMPLE,90000,Equity,2026-10-23,USD,EXAMPLE,Technology,,false,User\n'
            st.download_button('Download holdings CSV template',template,'holdings_template.csv')
            raw=upload.getvalue() if upload else (ROOT/'data/public/esgu_holdings.csv').read_bytes() if local else None
            if raw:
                try:bundle.update(import_holdings(raw))
                except Exception as e:st.error(f'Holdings import failed: {e}');bundle=None
            else:bundle=None;st.info('Upload holdings or select the downloaded ESGU holdings.')
        if bundle and 'snapshot' in bundle:
            st.caption(f"Valuation date: {bundle['snapshot']['as_of']}; cash: ${bundle['snapshot']['cash']:,.2f}; securities: {len(bundle['snapshot']['positions'])}.")
            with st.expander('Holdings and reference data',expanded=False):
                st.dataframe(pd.DataFrame(bundle['snapshot']['positions']).merge(pd.DataFrame(bundle['references']),on='security_id',how='left'),hide_index=True,width='stretch')
                st.caption('Issuer identity, ratings and ESG flags are not inferred from company names. Upload a supplemental reference CSV using matching security_id values; include references for new securities you intend to buy.')
                ref=st.file_uploader('Supplemental security reference CSV (optional)',type=['csv'],key='reference_v2')
                st.download_button('Download reference data template',pd.DataFrame(bundle['references']).to_csv(index=False),'references.csv')
                if ref:
                    try:
                        frame=pd.read_csv(ref,dtype=str).fillna('');new=[]
                        for row in frame.to_dict('records'):
                            row={k:(v or None) for k,v in row.items()}
                            esg=row.get('esg_excluded');row['esg_excluded']=None if esg is None else {'true':True,'false':False}[esg.lower()]
                            new.append(Security.model_validate(row).model_dump(mode='json'))
                        if len({r['security_id'] for r in new})!=len(new):raise ValueError('Reference data contains duplicate security IDs.')
                        merged={r['security_id']:r for r in bundle['references']};merged.update({r['security_id']:r for r in new});bundle['references']=list(merged.values())
                    except Exception as e:st.error(f'Invalid supplemental reference data; checks stopped: {e}');bundle=None
            if bundle:
                for issue in bundle.get('input_issues',[]):st.warning(issue)
                st.caption('Positive amounts buy; negative amounts sell. fee is the transaction cost. Leave trades empty to check current holdings only.')
                rows=pd.DataFrame(bundle['trades'],columns=['trade_id','security_id','delta_value','fee'])
                trades=st.data_editor(rows,num_rows='dynamic',hide_index=True,width='stretch',key='trades_v2_'+mode+'_'+bundle.get('holdings_sha256','demo'),column_config={'delta_value':st.column_config.NumberColumn('Buy/sell amount',required=True),'fee':st.column_config.NumberColumn('Fee',min_value=0,default=0)})
                try:
                    bundle['trades']=trades.to_dict('records');report=run(bundle,source,source_name)
                    a,b=st.columns(2);a.metric('Current holdings',report['before']['overall']);b.metric('After simulated trades',report['after']['overall'])
                    if report['after']['overall']=='PASS':st.success('Proposed trades pass the simulation within the supplied rules and data scope.')
                    else:st.warning('Proposed trades cannot be cleared automatically. Review breaches and unresolved items.')
                    st.caption('PASS: passed · FAIL: breach · UNKNOWN: insufficient data · REVIEW: manual review. Upload actual updated holdings after execution to check again.')
                    with st.expander('Current holdings: detailed results'):show_result(report['before'])
                    with st.expander('Adjusted portfolio: detailed results',expanded=True):show_result(report['after'])
                    st.success('Step 2 results are automatically available in step 3.')
                except Exception as e:report=None;st.error(f'Check incomplete: {e}')

with tabs[2]:
    st.subheader('Explain breaches and propose verifiable remediation trades')
    if report is None:st.info('Complete the holdings and trade checks in step 2 first.')
    else:
        st.write('Generate suggestions for the adjusted portfolio from step 2. Claude explains issues in plain English and proposes trades; the engine independently accounts for the trades and rechecks every rule.')
        fix=report['remediation']
        with st.expander('No API required: engine-generated sales-to-cash proposal',expanded=mode=='Teaching demo'):
            st.metric('Engine proposal verification',fix['result']['overall'])
            st.dataframe(pd.DataFrame(fix['trades']),hide_index=True,width='stretch')
            st.caption('Assumes fixed prices, zero fees, no slippage and fractional amounts; this is not return optimization. Sales cannot automatically resolve missing data or interpretation requirements.')
            show_result(fix['result'])
        if st.button('Ask Claude to explain breaches and propose remediation',disabled=not(key and model)):
            st.session_state.pop('memo_v2',None)
            with st.spinner('Claude is preparing an explanation and proposal; the engine will verify it next…'):
                try:st.session_state.memo_v2=explain_and_propose(report,key,model)
                except Exception as e:st.error(f'No valid proposal was generated: {type(e).__name__}. Proposals that fail format, trade or API validation are not marked compliant.')
        memo=st.session_state.get('memo_v2')
        if memo and memo['source_input_sha256']==report['input_sha256']:
            st.markdown(memo['explanation']);st.write(memo['rationale'])
            st.dataframe(pd.DataFrame(memo['trades']),hide_index=True,width='stretch')
            st.metric('Engine verification of the Claude proposal',memo['result']['overall'])
            if not memo['verified']:st.warning('This proposal does not achieve a full PASS. Resolve the following outstanding items.')
            show_result(memo['result'])
            st.download_button('Download Claude proposal and audit',json.dumps(memo,ensure_ascii=False,indent=2),'claude_remediation.json')
        st.divider()
        st.download_button('Download compliance report',html_report(report),'compliance_report.html','text/html')
        st.download_button('Download complete audit',json.dumps(report,ensure_ascii=False,indent=2),'audit.json')
        if st.button('Save report to outputs'):st.success(str(save_report(report)))

with tabs[3]:
    st.subheader('Public resources · iShares ESGU')
    st.write('Use the two PDFs in step 1 and the holdings CSV in step 2. These documents are kept separate from synthetic teaching rules.')
    for item in json.loads((ROOT/'data/public/manifest.json').read_text()):
        st.markdown(f"**{item['file']}** · [Official source]({item['url']})")
        st.download_button('Download '+item['file'],(ROOT/'data/public'/item['file']).read_bytes(),item['file'],key=item['file'])
    st.caption('The SAI and prospectus may cover several funds. Public holdings do not contain all reference data needed to check every constraint.')
