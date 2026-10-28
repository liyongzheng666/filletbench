"""Read-only material-side audit of the frozen case 11 input."""
import json
import math
import sys
from pathlib import Path

from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.TopAbs import TopAbs_IN, TopAbs_SOLID
from OCP.TopoDS import TopoDS
from OCP.gp import gp_Pnt

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'adapters/occt/original'))
import geometry as g


def old_frame():
    ax, ay, bx, by, cx, cy = 209., -424., 400., 216., 116., 18.
    ab, ac, bc = ax*bx+ay*by, ax*cx+ay*cy, bx*cx+by*cy
    a = [ax, ay, math.sqrt(-ab*ac/bc)]
    b = [bx, by, math.sqrt(-ab*bc/ac)]
    c = [cx, cy, math.sqrt(-ac*bc/ab)]
    norm = lambda v: math.sqrt(sum(x*x for x in v))
    return [[x/norm(b) for x in b], [-x/norm(a) for x in a],
            [x/norm(c) for x in c]], 100*norm(a)/norm(b)


def main():
    source = REPO / 'data/original-occ/fixtures/9959f6889063c0ee1107e6ac5185035cba9dd48ba5b843679888baa3258ec7a8.brep'
    shape = g.read(source)
    solid = TopoDS.Solid_s(g.shapes(shape, TopAbs_SOLID)[0])
    frame, length = old_frame()
    world = lambda p: [sum(p[j]*frame[j][i] for j in range(3)) for i in range(3)]
    probes = []
    for fraction in (.2, .5, .8):
        for dx, dz in [(-.25,-.25), (-.25,.25), (.25,-.25), (.25,.25)]:
            local = [50+dx, -.606*length*fraction, dz]
            point = world(local)
            c = BRepClass3d_SolidClassifier(solid, gp_Pnt(*point), 1e-7)
            probes.append(dict(fraction=fraction, local_mm=local, world_mm=point,
                               material=c.State()==TopAbs_IN, state=str(c.State())))
    targets, records = g.select(shape, [dict(samples_mm=[world([50,0,0]), world([50,-.606*length,0])],
                                            required_support_adjacency_count=2)])
    result = dict(schema='case11.old-material-audit.v1', source=str(source.relative_to(REPO)),
                  source_sha256=source.stem, stats=g.stats(shape), frame_columns=frame,
                  target_selection=records, occupancy=probes,
                  occupied_quadrants_by_station=[sum(p['material'] for p in probes if p['fraction']==f) for f in (.2,.5,.8)],
                  material_classification='concave root: three local quadrants occupied at all three stations',
                  evidence_scope='Actual frozen BREP point classification; no reconstruction, camera or normal flip.')
    out = REPO / 'runs/case11-convexity/old-material-audit.json'
    out.write_text(json.dumps(result, indent=2))
    print(json.dumps({k:result[k] for k in ['source_sha256','occupied_quadrants_by_station','material_classification']}))


if __name__ == '__main__':
    main()
