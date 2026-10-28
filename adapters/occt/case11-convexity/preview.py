"""Self-contained, local-only candidate review with actual mesh and section."""
import base64
import html
import json
import math
from pathlib import Path
import sys

from PIL import Image, ImageDraw
from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
from OCP.TopAbs import TopAbs_EDGE
from OCP.TopoDS import TopoDS
from OCP.gp import gp_Pln, gp_Pnt, gp_Dir

import build


def raster(mesh, camera, path, scale=None):
    w,h=980,780
    dot=lambda a,b:sum(x*y for x,y in zip(a,b))
    projection=lambda p:[dot(p,camera['screen_right']),-dot(p,camera['screen_up']),dot(p,camera['toward_viewer'])]
    pts=[projection(p) for p in mesh['vertices']]
    lo=[min(p[i] for p in pts) for i in range(2)];hi=[max(p[i] for p in pts) for i in range(2)]
    scale=scale or min((w-160)/(hi[0]-lo[0]),(h-130)/(hi[1]-lo[1]))
    center=[(lo[i]+hi[i])/2 for i in range(2)]
    screen=lambda p:[(p[0]-center[0])*scale+w/2,(p[1]-center[1])*scale+h/2,p[2]]
    pts=[screen(p) for p in pts]
    image=Image.new('RGB',(w,h),'#fcfcf8');pix=image.load();zbuf=[-1e30]*(w*h);triangle_edge_uses={}
    for ids in mesh['triangles']:
        a,b,c=[pts[i] for i in ids]
        den=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
        if abs(den)<1e-10:continue
        raw=[mesh['vertices'][i] for i in ids];u=[raw[1][i]-raw[0][i] for i in range(3)];v=[raw[2][i]-raw[0][i] for i in range(3)]
        n=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
        facing=dot(n,camera['toward_viewer'])
        for ia,ib in [(ids[0],ids[1]),(ids[1],ids[2]),(ids[2],ids[0])]:
            triangle_edge_uses.setdefault(tuple(sorted((ia,ib))),[]).append(facing)
        norm=math.sqrt(dot(n,n));light=abs(dot(n,[.2,-.45,.87])/max(norm,1e-30));bright=.77+.23*light
        color=tuple(int(x*bright) for x in (255,218,52))
        xmin=max(0,int(min(a[0],b[0],c[0])));xmax=min(w-1,math.ceil(max(a[0],b[0],c[0])))
        ymin=max(0,int(min(a[1],b[1],c[1])));ymax=min(h-1,math.ceil(max(a[1],b[1],c[1])))
        for y in range(ymin,ymax+1):
            for x in range(xmin,xmax+1):
                s=((b[1]-c[1])*(x+.5-c[0])+(c[0]-b[0])*(y+.5-c[1]))/den
                t=((c[1]-a[1])*(x+.5-c[0])+(a[0]-c[0])*(y+.5-c[1]))/den
                r=1-s-t
                if min(s,t,r)<-1e-8:continue
                depth=s*a[2]+t*b[2]+r*c[2];idx=y*w+x
                if depth>zbuf[idx]:zbuf[idx]=depth;pix[x,y]=color
    draw=ImageDraw.Draw(image)
    def edge(lines,color,width,tolerance=.16):
        for line in lines:
            points=[screen(projection(p)) for p in line]
            for a,b in zip(points,points[1:]):
                count=max(2,int(math.hypot(a[0]-b[0],a[1]-b[1])*2))
                for i in range(count+1):
                    f=i/count;q=[a[k]+f*(b[k]-a[k]) for k in range(3)];x,y=round(q[0]),round(q[1])
                    if 0<=x<w and 0<=y<h and q[2]>=zbuf[y*w+x]-tolerance:
                        draw.ellipse((x-width/2,y-width/2,x+width/2,y+width/2),fill=color)
    edge(mesh['edges'],'#151711',2)
    # An apparent contour inside a curved face is not a BREP edge. Add only
    # actual adjacent mesh triangles whose oriented facing signs differ.
    apparent_contours=[[mesh['vertices'][i] for i in pair] for pair,signs in triangle_edge_uses.items()
                       if len(signs)==2 and signs[0]*signs[1]<0]
    edge(apparent_contours,'#151711',2,1.5)
    edge(mesh.get('selected_edges',[]),'#e81b24',4)
    image.save(path)


def section(out):
    shape=build.g.read(out/'before.brep')
    op=BRepAlgoAPI_Section(shape,gp_Pln(gp_Pnt(0,-30,0),gp_Dir(0,1,0)),False);op.Build()
    lines=[build.g.edge_record(op.Shape(),TopoDS.Edge_s(e))['polyline'] for e in build.g.shapes(op.Shape(),TopAbs_EDGE)]
    (out/'section-y-minus30.json').write_text(json.dumps(dict(plane_y_mm=-30,actual_section_brep=True,edges=lines),indent=2))
    width,height=980,560
    p=lambda x,z:(75+(x+25)*5.7,80-z*6.7)
    paths=[]
    for line in lines:
        paths.append('<polyline fill="none" stroke="#373f44" stroke-width="2" points="'+' '.join(f'{p(q[0],q[2])[0]},{p(q[0],q[2])[1]}' for q in line)+'"/>')
    x,z=p(50,0)
    paths.append(f'<circle cx="{x}" cy="{z}" r="7" fill="#e5232a"/><text x="{x-70}" y="{z-25}" fill="#b31922">目标 (50, 0)</text>')
    for q in [(-1,-1),(-1,1),(1,-1),(1,1)]:
        sx,sy=p(50+q[0]*3, q[1]*3)
        paths.append(f'<circle cx="{sx}" cy="{sy}" r="4" fill="'+('#1d996b' if q==(-1,-1) else '#fff')+'" stroke="#1d996b"/>')
    paths.extend(['<text x="75" y="515">实际 y = −30 mm 剖面。红点左下方为实材；其余三个局部象限为空。</text>',
                  '<text x="75" y="540">全截面来自 BRepAlgoAPI_Section；圆点示意材料象限，精确 0.25 mm 探针数据见 report.json。</text>'])
    svg=f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="#fcfcf8"/><g font-family="sans-serif" font-size="18">'+''.join(paths)+'</g></svg>'
    (out/'section.svg').write_text(svg)
    return svg


def main():
    out=(Path(sys.argv[1]) if len(sys.argv)>1 else build.REPO/'runs/case11-convexity/candidate-v6').resolve()
    report=json.loads((out/'report.json').read_text())
    for rel,name in [('before.mesh.json','main.png'),('r1/result.mesh.json','r1.png'),('r3/result.mesh.json','r3.png'),('r6/result.mesh.json','r6-invalid.png')]:
        if (out/rel).exists():
            mesh=json.loads((out/rel).read_text());raster(mesh,report['camera'],out/name)
    svg=section(out)
    png=lambda name:'data:image/png;base64,'+base64.b64encode((out/name).read_bytes()).decode()
    rows=''.join('<tr><td>R'+str(int(a['radius_mm']))+'</td><td>'+str(a['native_done'])+'</td><td>'+str(a.get('inspection',{}).get('passed','未取得实体'))+'</td><td>'+str(a.get('step',{}).get('readback',{}).get('passed','未导出'))+'</td><td>'+html.escape(a['status'])+'</td></tr>' for a in report['attempts'])
    captions={'before':'输入：物理凸肩。高面、下降窄面、低面及横向过渡带仍需对照本地 PDF。'}
    for a in report['attempts']:
        k='r'+str(int(a['radius_mm']))
        captions[k]=(k.upper()+'：native 完成，BREP/BOP 与 STEP 回读通过；形状未验收。' if a['status']=='native_candidate' else
                     k.upper()+'：IsDone=true，但实体/BOP 无效且有自交；失败实体保留。' if a['native_done'] else
                     k.upper()+'：native 构建失败，未取得结果实体；仍显示输入。')
    attempt_note=' '.join(captions['r'+str(int(a['radius_mm']))] for a in report['attempts'])
    page='''<!doctype html><meta charset="utf-8"><title>Case 11｜凸肩候选与材料剖面</title>
<style>body{font:17px/1.6 system-ui;color:#243332;background:#eef1eb;margin:0}main{max-width:1200px;margin:auto;padding:30px}h1{font-size:30px}h2{font-size:21px}.notice{background:#fff2c9;border-left:5px solid #d49718;padding:15px 20px}article{background:white;border-radius:10px;margin:20px 0;padding:20px}img{width:100%;display:block}table{border-collapse:collapse;width:100%}td,th{text-align:left;border-bottom:1px solid #ddd;padding:8px}button{font:inherit;padding:8px 16px;margin-right:8px;cursor:pointer}.muted{color:#687974}code{font-size:.9em}</style>
<main><h1>Case 11｜凸肩候选与实际材料剖面</h1>
<p class="notice">'''+html.escape(report['revision'])+'''：'''+html.escape(report['geometry_status'])+'''。红色目标改为真实凸外棱；尺寸、厚度与隐藏连接均为推定。原 PDF 与截图未复制到交付目录。</p>
<article><h2>1. 主视图与实际 native 结果</h2><p>物理直角坐标构造；只改变相机。A/C 高平面 z=0，B 低平面 z=−40。红边固定为 x=50, z=0, y∈[−60.6,0]。</p>
<div><button data-show="before">输入红目标</button><button data-show="r1">R1</button><button data-show="r3">R3</button><button data-show="r6">R6</button></div>
<img id="view" alt="凸肩候选主视图"><p id="caption" class="muted"></p><p class="muted">黑线包含实际 BREP 边与原生三角网格相邻三角片的可见性翻转轮廓；曲面内部的轮廓线不是新增 CAD 边。</p></article>
<article><h2>2. 从实体求得的横剖面</h2>'''+svg+'''
<p>在 y=−12/−30/−48 三个站位，以目标为中心探测 x、z 各 ±0.25 mm。新候选每站仅一个实材象限；冻结旧模型每站三个。此结论独立于相机和三角网格法向。</p></article>
<article><h2>3. 实际验证记录</h2><table><thead><tr><th>半径 mm</th><th>IsDone</th><th>BREP/BOP</th><th>STEP 回读/BOP</th><th>状态</th></tr></thead><tbody>'''+rows+'''</tbody></table>
<p>'''+attempt_note+'''仍不代表参考外形通过或 repair_fa_X 功能等价。</p>
<p>输入每条边恰有两个不同邻面与两次面环使用：'''+str(report['before'].get('manifold_audit',{}).get('passed','未检查'))+'''。此门槛独立于 BRepCheck/BOP。</p>
<p><a href="before.brep">输入 BREP</a> · <a href="before.step">输入 STEP</a> · <a href="report.json">完整报告</a> · <a href="section-y-minus30.json">实际剖面曲线</a></p></article>
<article><h2>4. 必须复核的推定</h2><p>3 mm 主体薄板、短舌向下加厚、左开口与隐藏连通、40 mm 台阶深度、既有曲带圆弧均未由 PDF 尺寸标定。候选使用一个实体且红边连续，但这些条件不能证明整体重建忠实。</p></article></main>
<script>const images='''+json.dumps({k:png(v if (out/v).exists() else 'main.png') for k,v in [('before','main.png'),('r1','r1.png'),('r3','r3.png'),('r6','r6-invalid.png')]})+''';const captions='''+json.dumps(captions)+''';function show(k){document.querySelector('#view').src=images[k];document.querySelector('#caption').textContent=captions[k]}document.querySelectorAll('button').forEach(b=>b.onclick=()=>show(b.dataset.show));show('before');</script>'''
    (out/'index.html').write_text(page)
    print(out/'index.html')


if __name__=='__main__':main()
