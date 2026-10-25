"""Documents are untrusted data. Exact evidence and file hashes anchor review."""
import hashlib
import io
import subprocess
import tempfile
from pathlib import Path

def digest(data):
    return hashlib.sha256(data).hexdigest()

def extract_text(data: bytes, name: str):
    if len(data)>20_000_000: raise ValueError('Document exceeds 20 MB.')
    if name.lower().endswith('.pdf'):
        try:
            from pypdf import PdfReader
            pages=[p.extract_text() or '' for p in PdfReader(io.BytesIO(data)).pages]
        except ImportError:
            with tempfile.TemporaryDirectory() as tmp:
                source=Path(tmp)/'source.pdf';source.write_bytes(data)
                p=subprocess.run(['pdftotext','-layout',str(source),'-'],capture_output=True,check=True,timeout=60)
                pages=p.stdout.decode('utf-8').split('\f')
        text='\n'.join(f'[PDF page {i+1}]\n{p}' for i,p in enumerate(pages))
    else: text=data.decode('utf-8-sig')
    if len(text.strip())<30: raise ValueError('No usable text. Scanned PDFs need OCR before extraction.')
    return text

def validate_evidence(book, data, text):
    if book.source_sha256 != digest(data): raise ValueError('Rulebook source hash does not match the uploaded document.')
    norm=lambda x:' '.join(x.split())
    for rule in book.rules:
        if not rule.evidence_verified:
            if rule.needs_review and not rule.approved:
                continue  # Quarantined candidate, never eligible for automatic clearance.
            raise ValueError(f'{rule.id}: unverified evidence cannot be approved.')
        if norm(rule.evidence) not in norm(text):
            raise ValueError(f'{rule.id}: quoted evidence is absent from the source. Correct it before checking.')
