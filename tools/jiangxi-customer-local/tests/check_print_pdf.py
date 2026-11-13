"""Verify the fictional 12-month PDF exported by tests/print.cjs."""
import sys,re,unicodedata
from pypdf import PdfReader
r=PdfReader(sys.argv[1]);texts=[unicodedata.normalize('NFKC',p.extract_text() or '') for p in r.pages]
t=re.sub(r'\s+','',''.join(texts))
assert '账单核对与分时用电结构' in t
assert '测算依据与待确认事项' not in t
assert '3,600' in t and '谷段' in t and '深谷段' in t and '2026-12' in t
assert all(len(p.strip())>10 for p in texts),'Unexpected blank page'
assert r.metadata.title=='示例市演示0联动0服务用电测算报告'
print('PASS full structure, last month, valley shares, title and no empty pages:',len(r.pages))
