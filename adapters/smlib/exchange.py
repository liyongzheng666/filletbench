"""Validated exact NURBS token exchange; no automatic geometry repair."""
import math

def finite(v):
 v=float(v)
 if not math.isfinite(v):raise ValueError('nonfinite geometry')
 return format(v,'.17g')
def line(*xs):return ' '.join(str(x) if isinstance(x,(str,int)) else finite(x) for x in xs)
def check_knots(knots,npoles,degree):
 if len(knots)!=npoles+degree+1:raise ValueError(f'full-knot count {len(knots)} != poles+degree+1 {npoles+degree+1}')
 if any(float(b)<float(a) for a,b in zip(knots,knots[1:])):raise ValueError('decreasing knot vector')
 if degree<1 or npoles<=degree:raise ValueError('invalid NURBS degree/pole count')
 if not (all(abs(float(v)-float(knots[degree]))<1e-12 for v in knots[:degree+1]) and all(abs(float(v)-float(knots[-degree-1]))<1e-12 for v in knots[-degree-1:])):raise ValueError('unclamped periodic NURBS requires exact finite-domain conversion upstream; not silently repaired')
def encode(c):
 vs=c['vertices'];es=c['edges'];shells=c['shells'];kind=c['kind']
 if kind not in ('solid','shell','face'):raise ValueError('unsupported component kind '+str(kind))
 vids={v['id'] for v in vs};eids={e['id'] for e in es}
 if len(vids)!=len(vs) or len(eids)!=len(es):raise ValueError('duplicate vertex/edge ID')
 rows=['SMX1','1',line('COMP',1,1 if kind=='solid' else 0,float(c.get('tolerance',1e-7)),len(vs),len(es),len(shells))]
 for v in vs:rows.append(line('V',v['id'],*map(float,v['point']),float(v.get('tolerance',c.get('tolerance',1e-7)))))
 for e in es:
  if e.get('degenerated'):raise ValueError('degenerated/pole edge unsupported by this local topdown adapter; not deleted')
  if any(v not in vids for v in e['vertices']):raise ValueError('edge has missing vertex')
  curve=e['curve'];poles=curve['poles'];weights=curve.get('weights',[1.]*len(poles));degree=int(curve['degree']);knots=curve['knots'];check_knots(knots,len(poles),degree)
  if len(weights)!=len(poles):raise ValueError('curve weight count')
  if not e['range'][0]<e['range'][1]:raise ValueError('unordered edge range')
  rows.append(line('E',e['id'],*e['vertices'],*map(float,e['range']),float(e.get('tolerance',c.get('tolerance',1e-7))),degree,len(poles),len(knots)))
  for p,w in zip(poles,weights):
   w=float(w)
   if w<=0:raise ValueError('nonpositive NURBS weight')
   rows.append(line(*[float(a)*w for a in p],w))
  rows.append(line(*map(float,knots)))
 for sh in shells:
  faces=sh['faces'];rows.append(line('SH',int(sh.get('is_void',False)),int(sh.get('closed',kind=='solid')),len(faces)))
  for f in faces:
   if f['orientation'] not in (1,-1):raise ValueError('face orientation must +/-1')
   s=f['surface'];p=s['poles'];nu=len(p);nv=len(p[0]);weights=s.get('weights',[[1.]*nv for _ in range(nu)]);ku=s['knots_u'];kv=s['knots_v'];pu=int(s['degree_u']);pv=int(s['degree_v']);check_knots(ku,nu,pu);check_knots(kv,nv,pv)
   if any(len(row)!=nv for row in p):raise ValueError('nonrectangular surface poles')
   if len(weights)!=nu or any(len(row)!=nv for row in weights):raise ValueError('surface weight count')
   domain=s['domain'];loops=f['loops'];rows.append(line('F',f['id'],f['orientation'],pu,pv,nu,nv,len(ku),len(kv),*map(float,domain),len(loops)))
   for pr,wr in zip(p,weights):
    for xyz,w in zip(pr,wr):
     w=float(w)
     if w<=0:raise ValueError('nonpositive surface weight')
     rows.append(line(*[float(a)*w for a in xyz],w))
   rows.append(line(*map(float,ku)));rows.append(line(*map(float,kv)))
   if not loops or not loops[0].get('outer'):raise ValueError('first loop must be outer')
   for loop in loops:
    uses=loop['edges'];direction=loop.get('orientation',-1 if loop.get('source_orientation')=='Reversed' else 1 if loop.get('source_orientation')=='Forward' else 1 if loop['outer'] else -1)
    if direction not in (1,-1):raise ValueError('loop orientation must +/-1')
    rows.append(line('L',int(loop['outer']),direction,len(uses)))
    for u in uses:
     if u['id'] not in eids or u['orientation'] not in (1,-1):raise ValueError('invalid coedge reference/orientation')
     rows.append(line(u['id'],u['orientation']))
 return '\n'.join(rows)+'\n'
