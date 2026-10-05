"""Inspect the entire candidate release, not just rendered text or ignore rules."""
from __future__ import annotations
import argparse
import ast
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from public_ui.schema import SENSITIVE,PublicDataError,validate
from public_ui.package import PublicPackage

EXCLUDE={'.git','__pycache__','.pytest_cache','.venv','verification'}
ALLOWED_SUFFIXES={'.py','.md','.json','.gz','.txt','.toml'}
def inspect_tree(root):
    root=Path(root);files=[];errors=[]
    for path in sorted(root.rglob('*')):
        rel=path.relative_to(root)
        if any(p in EXCLUDE for p in rel.parts):continue
        if path.is_symlink():errors.append({'file':str(rel),'reason':'symlink_not_permitted'});continue
        if not path.is_file():continue
        if path.name in {'.gitignore','.dockerignore','Dockerfile'}:allowed=True
        else:allowed=path.suffix in ALLOWED_SUFFIXES
        if not allowed:errors.append({'file':str(rel),'reason':'unapproved_file_type'});continue
        raw=path.read_bytes()
        if path.suffix=='.gz':raw=gzip.decompress(raw)
        try:text=raw.decode('utf-8')
        except UnicodeError:errors.append({'file':str(rel),'reason':'unknown_binary'});continue
        # Security implementation may contain pattern prefixes; never real identity paths.
        if path.suffix in {'.json','.gz','.md','.txt','.toml'} and SENSITIVE.search(text):
            errors.append({'file':str(rel),'reason':'sensitive_text'});
        if path.suffix=='.py':
            tree=ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node,(ast.Import,ast.ImportFrom)):
                    names=[n.name for n in node.names] if isinstance(node,ast.Import) else [node.module or '']
                    if any(n=='src' or n.startswith(('src.','presentation.')) for n in names):
                        errors.append({'file':str(rel),'reason':'private_or_business_import'})
                if isinstance(node,ast.Constant) and isinstance(node.value,str):
                    if re.search(r'(?:/(?:Users|home)/[A-Za-z0-9_.\-\u4e00-\u9fff]+/|[A-Za-z]:\\Users\\)',node.value):
                        errors.append({'file':str(rel),'reason':'private_identity_path'})
                    if re.search(r'gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|BEGIN (?:RSA |OPENSSH )?PRIVATE KEY',node.value):
                        errors.append({'file':str(rel),'reason':'credential_literal'})
        files.append({'path':str(rel),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size})
    package=PublicPackage(root);package.all_valid()
    index=package.read('storage/index.json')
    if len(index['rows'])!=1600:errors.append({'file':'storage/index','reason':'strategy_sample_count_changed'})
    # Across all accessible branches: no raw price field or reversible interval cash/volume pair.
    a_days=0;b_groups=0
    for name,item in package.files.items():
        obj=package.read(name)
        if item['kind']=='a_day':
            a_days+=1
            for s in obj['strategies']:
                if len(s['actions'])!=96 or len(s['original_plan'])!=96:errors.append({'file':name,'reason':'action_grid_changed'})
                for row in [*s['actions'],*s['original_plan'],*s['explanations']]:
                    if any(('price' in k and k not in {'execution_price_target','future_actual_price_used'}) or k.endswith('amount_yuan') for k in row):
                        errors.append({'file':name,'reason':'private_interval_price_or_cash'})
                        break
        elif item['kind']=='b_group':
            b_groups+=1
            if obj['group']!='synthetic_2026-08':
                if any(s['inputs'] or s['submissions'] or s['monitor'] or s['details_available'] for s in obj['strategies']):
                    errors.append({'file':name,'reason':'private_interval_input'})
                if any(case['lines'] for case in obj['stress']):errors.append({'file':name,'reason':'private_pressure_lines'})
    if a_days!=200 or b_groups!=3:errors.append({'file':'package','reason':'case_sample_coverage_changed'})
    errors=list({(e['file'],e['reason']):e for e in errors}.values())
    return {'status':'PASS' if not errors else 'FAIL','files':len(files),'bytes':sum(x['bytes'] for x in files),
            'node_days':a_days,'strategy_days':len(index['rows']),'generation_groups':b_groups,
            'direct_native_input_exposure':False if not errors else 'not_certified',
            'review_scope':'explicit_schema + native_sequences + known_interval_reconstruction; not_formal_non_inference',
            'findings':errors,'release_files':files}

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,default=ROOT);ap.add_argument('--output',type=Path)
    args=ap.parse_args();report=inspect_tree(args.root)
    if args.output:args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    compact={k:v for k,v in report.items() if k not in {'release_files','findings'}}
    compact['finding_count']=len(report['findings']);compact['findings']=report['findings'][:20]
    print(json.dumps(compact,ensure_ascii=False))
    if report['status']!='PASS':raise SystemExit(1)
