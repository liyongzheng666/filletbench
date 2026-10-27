"""Check frozen inputs, viewer resource closure and publication boundaries."""
import pathlib,json,hashlib,re,sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    errors=[];cases=json.loads((ROOT/'data/corpus.json').read_text())['cases'];numbers=[c['number'] for c in cases]
    if numbers!=list(range(1,29))+[30,31,33,34,35,36]:errors.append('stable case numbering changed')
    jobs=list((ROOT/'data/jobs').glob('*.json'))
    if len(jobs)!=104:errors.append('expected 104 ordinary requests')
    for path in jobs:
        d=json.loads(path.read_text())
        for key,h in [('source_brep','source_sha256'),('source_fixture_json','source_fixture_sha256'),('source_contract_file','source_contract_sha256')]:
            f=ROOT/d[key]
            if not f.is_file() or sha(f)!=d[h]:errors.append(f'{path.name}: {key} identity mismatch')
        if d.get('native_edge_indices_supplied'):errors.append(f'{path.name}: foreign native edge indices')
    for base in ['data','adapters','tools','docs','web']:
        for path in (ROOT/base).rglob('*'):
            if not path.is_file() or any(p in path.parts for p in ['__pycache__','build','node_modules']):continue
            if path.suffix.lower() in ['.pdf','.png','.jpg','.jpeg','.gif','.webp','.smb','.dylib','.so','.dll','.fcstd']:errors.append(f'forbidden publication asset: {path.relative_to(ROOT)}')
            if path.suffix in ['.py','.cpp','.h','.md','.json','.html','.js','.css','.yml'] and 'vendor' not in path.parts:
                s=path.read_text(errors='replace')
                # Catch private home paths and well-known credential formats without printing values.
                if re.search(r'/Users/[A-Za-z][^\s/]+/',s):errors.append(f'private home path: {path.relative_to(ROOT)}')
                if re.search(r'gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}',s):errors.append(f'credential-like material: {path.relative_to(ROOT)}')
    catalog=ROOT/'web/data/catalog.json'
    if catalog.exists():
        for c in json.loads(catalog.read_text())['cases']:
            d=json.loads((ROOT/'web'/c['data']).read_text())
            for v in d['variants']:
                for field in ['input_mesh']:
                    if v.get(field) and not (ROOT/'web'/v[field]).is_file():errors.append(f'missing {v[field]}')
                for eng in ['occt','smlib']:
                    for field in ['mesh','before_mesh','summary','quality_audit']:
                        f=v.get(eng,{}).get(field)
                        if f and not (ROOT/'web'/f).is_file():errors.append(f'missing {f}')
                    if v.get(eng,{}).get('special_feature_passed') is True:errors.append(f'{v["id"]}: unexpected blanket source-feature pass')
    if errors:
        print('\n'.join(errors));return 1
    print(f'OK: {len(cases)} stable cases, {len(jobs)} request identities, publication/resource checks. No functional pass inferred.');return 0
if __name__=='__main__':sys.exit(main())
