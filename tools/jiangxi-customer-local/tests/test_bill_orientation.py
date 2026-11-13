"""Synthetic orientation and fee-label regressions. No customer documents."""
import io,sys,unittest,tempfile
from unittest.mock import patch
from decimal import Decimal
from pathlib import Path
from pypdf import PdfReader,PdfWriter
from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
import pdfplumber
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'python'))
from bills import normalize_pdf,purchase_fee,Store,PARSER_REVISION

def fixture(turn=0,baked=False):
    w=PdfWriter();p=w.add_blank_page(600,800)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    p[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
    stream=DecodedStreamObject()
    # The diagonal watermark deliberately outnumbers the real text.
    stream.set_data(b'BT /F1 10 Tf 1 0 0 1 20 700 Tm (Invoice total 1234.56 Quantity 9876.54 Account DEMO1234) Tj ET\n'+b'BT /F1 10 Tf .93969 .34202 -.34202 .93969 20 200 Tm ('+b'WATERMARK '*20+b') Tj ET')
    p[NameObject('/Contents')]=w._add_object(stream);p.rotate(turn)
    if baked:p.transfer_rotation_to_content()
    out=io.BytesIO();w.write(out);return out.getvalue()

class BillOrientation(unittest.TestCase):
    def test_cardinal_rotations_with_larger_diagonal_watermark(self):
        for baked in [False,True]:
            for turn in [0,90,180,270]:
                with self.subTest(turn=turn,baked=baked):
                    raw=fixture(turn,baked);normalized,changes=normalize_pdf(raw)
                    with pdfplumber.open(io.BytesIO(normalized)) as pdf:
                        clean=pdf.pages[0].filter(lambda o:o.get('object_type')!='char' or abs(o.get('matrix',(1,0,0,1,0,0))[1])<.01)
                        text=clean.extract_text() or ''
                    self.assertIn('1234.56',text);self.assertIn('9876.54',text)
                    self.assertNotIn('WATERMARK',text)
                    self.assertEqual(bool(changes),bool(turn))
                    again,changes_again=normalize_pdf(normalized)
                    self.assertEqual(again,normalized);self.assertFalse(changes_again)
                    self.assertEqual(raw,fixture(turn,baked))
    def test_fee_labels_whitespace_decimal_and_prefix(self):
        for label in ['代理购电电费','已入市的市场化购电电费','市场化购电电费','零售交易电费']:
            for text in [label+' 12,345.67\n输配电费 99', ' '.join(label)+'\n12,345.67\n输配电费 99']:
                self.assertEqual(purchase_fee(text)[1],Decimal('12345.67'))
        self.assertEqual(purchase_fee('零售交易电费 -0.01')[1],Decimal('-.01'))
        self.assertEqual(purchase_fee('市场化购电电费 0.00')[1],Decimal(0))
        self.assertEqual(purchase_fee('其中：(1)代理购电电费 12345.67 5.平均电价')[1],Decimal('12345.67'))
    def test_conflicting_or_ambiguous_fees_block(self):
        for text in ['本期电费 123.45','代理购电电费 1.00\n零售交易电费 2.00','零售交易电费 1.00\n零售交易电费 2.00','零售交易电费 1,234 0.33 407.22']:
            self.assertIsNone(purchase_fee(text)[1])
    def test_failed_file_retry_once_per_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(tmp);sha='a'*64;(store.originals/(sha+'.pdf')).write_bytes(fixture())
            store.save({'records':[],'files':[{'hash':sha,'suffix':'.pdf','name':'test.pdf','error':'旧错误'}]})
            with patch('bills.extract_pdf',side_effect=ValueError('扫描件')) as extract:
                store.reprocess_pending();store.reprocess_pending()
                self.assertEqual(extract.call_count,1)
            self.assertEqual(store.load()['files'][0]['parser_revision'],PARSER_REVISION)
    def test_recovered_rotated_duplicate_not_counted_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(tmp);sha='a'*64;(store.originals/(sha+'.pdf')).write_bytes(fixture(90))
            row={'id':'same-bill','hash':'b'*64,'account':'DEMO','parser_revision':PARSER_REVISION,'issues':[]}
            store.save({'records':[row],'files':[{'hash':sha,'suffix':'.pdf','name':'test.pdf','error':'旧错误'}]})
            with patch('bills.extract_pdf',return_value=[dict(row,hash=sha)]):data=store.reprocess_pending()
            self.assertEqual(len(data['records']),1);self.assertIsNone(data['files'][0]['error'])
            self.assertEqual(data['files'][0]['added'],0)

if __name__=='__main__':unittest.main()
