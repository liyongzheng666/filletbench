"""Publish derived OCCT special protocols separately from matched ordinary jobs."""
import pathlib,json,argparse
from build_site import ROOT,WEB,read,write,sanitize,mesh,digest

def main():
 p=argparse.ArgumentParser();p.add_argument('--runs',default='runs/fresh-occt-special');a=p.parse_args();base=ROOT/a.runs;idx=read(base/'index.json');cases={}
 for row in idx['results']:
  sp=base/row['summary'];s=read(sp);run=sp.parent;n=s['case_number'];dst=WEB/f'data/occt-special/{s["job_id"]}';write(dst/'summary.json',sanitize(s));before=mesh(run/'before.mesh.json');after=mesh(run/'result.mesh.json');composite=s['method_kind']=='explicit_occ_composition'
  label=('组合 G2 代理 · α='+str(s.get('parameters',{}).get('proxy_alpha'))) if composite else 'OCCT 衍生协议 · '+s['job_id'].split('special.')[-1]
  reason='固定接触条件下的显式 Bézier 组合；接缝曲率子判据通过，α 是本地代理参数，不等同于原 PDF softness。' if composite else '对衍生/缝合输入调用原生边圆角；未编码原图的 face-face、master、sense、trim 或 softness 协议。'
  targets=s.get('selection',[])
  v={'id':s['protocol_id'],'label':label,'radius_mm':s.get('radius_mm'),'role':'explicit_composition' if composite else 'derived_input_control','note':reason,'pairing':'unmatched_special_protocol','input_mesh':before,'targets':targets,'special_protocol_verified':False,'input_construction_note':s['description'],'occt':{'status':'candidate_unverified','label':'组合子判据通过' if composite else '原生候选 · 衍生输入','reason':reason,'mesh':after,'before_mesh':before,'summary':(dst/'summary.json').relative_to(WEB).as_posix(),'version':s['engine_version'],'method':'composite' if composite else 'native_edge_fillet','method_label':'显式 G2 组合' if composite else '衍生输入 / 原生边圆角','metrics':s.get('result_stats'),'reproduce':f'python bench.py special --engine occt --case {n}','source_sha256':s['source_sha256'],'evidence_kind':'fresh_derived_protocol','special_feature_passed':False},'smlib':{'status':'not_run','label':'不同协议','reason':'这条 OCCT 衍生/组合路线没有成对 SMLib 调用；切换 SMLib 特殊协议查看其实际结果。','method':'unmatched_protocol','mesh':None}}
  cases.setdefault(str(n),[]).append(v)
 write(WEB/'data/occt-special/index.json',{'schema_version':1,'cases':cases,'count':len(idx['results']),'same_protocol_as_smlib':False});print('published',len(idx['results']),'derived OCCT views')
if __name__=='__main__':main()
