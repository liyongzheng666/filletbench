"""Verify visible transition convexity from actual BREP surfaces/material."""
import json
from pathlib import Path
import sys
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepTools import BRepTools
from OCP.BRepLProp import BRepLProp_SLProps
from OCP.BRepClass3d import BRepClass3d_SolidClassifier
from OCP.GeomAbs import GeomAbs_Cylinder
from OCP.TopAbs import TopAbs_FACE, TopAbs_SOLID, TopAbs_REVERSED, TopAbs_IN
from OCP.TopoDS import TopoDS
from OCP.gp import gp_Pnt
import build


def main():
    out=(Path(sys.argv[1]) if len(sys.argv)>1 else build.REPO/'runs/case11-convexity/candidate-v6').resolve()
    shape=build.g.read(out/'before.brep');solid=TopoDS.Solid_s(build.g.shapes(shape,TopAbs_SOLID)[0]);rows=[]
    for i,raw in enumerate(build.g.shapes(shape,TopAbs_FACE),1):
        face=TopoDS.Face_s(raw);surf=BRepAdaptor_Surface(face)
        if surf.GetType()!=GeomAbs_Cylinder:continue
        uv=BRepTools.UVBounds_s(face);u,v=(uv[0]+uv[1])/2,(uv[2]+uv[3])/2
        props=BRepLProp_SLProps(surf,u,v,2,1e-10);point=props.Value();n=props.Normal()
        sign=-1 if face.Orientation()==TopAbs_REVERSED else 1
        if sign<0:n.Reverse()
        xyz=build.g.xyz(point);normal=build.g.xyz(n);axis=surf.Cylinder().Axis();center=surf.Cylinder().Location()
        radial=[xyz[0]-xyz[0],xyz[1]-center.Y(),xyz[2]-center.Z()]
        normal_radial=sum(x*y for x,y in zip(normal,radial))/surf.Cylinder().Radius()
        probes=[]
        for distance in (-.25,.25):
            q=[x+distance*z for x,z in zip(xyz,normal)];classifier=BRepClass3d_SolidClassifier(solid,gp_Pnt(*q),1e-7)
            probes.append(dict(signed_outward_offset_mm=distance,point_mm=q,inside=classifier.State()==TopAbs_IN,state=str(classifier.State())))
        curvatures=[sign*props.MinCurvature(),sign*props.MaxCurvature()]
        rows.append(dict(face_index_1based=i,point_mm=xyz,outward_normal=normal,cylinder_radius_mm=surf.Cylinder().Radius(),
                         cylinder_axis_direction=build.g.xyz(axis.Direction()),cylinder_axis_location_mm=build.g.xyz(center),
                         outward_normal_dot_radial=normal_radial,oriented_principal_curvatures_mm_inverse=curvatures,
                         material_probes=probes,geometry='convex outer cylinder' if normal_radial>.99 else 'concave inner cylinder'))
    visible=[r for r in rows if r['outward_normal_dot_radial']>.99 and r['point_mm'][0]>50]
    scale_samples=[]
    faces=build.g.shapes(shape,TopAbs_FACE)
    for item in visible:
        face=TopoDS.Face_s(faces[item['face_index_1based']-1]);surface=BRepAdaptor_Surface(face)
        uv=BRepTools.UVBounds_s(face);sign=-1 if face.Orientation()==TopAbs_REVERSED else 1
        for uf in (.2,.5,.8):
            for vf in (.2,.5,.8):
                props=BRepLProp_SLProps(surface,uv[0]+uf*(uv[1]-uv[0]),uv[2]+vf*(uv[3]-uv[2]),2,1e-10)
                p=build.g.xyz(props.Value());n=props.Normal()
                if sign<0:n.Reverse()
                n=build.g.xyz(n)
                for scale in (.05,.25,1.):
                    states=[]
                    for d in (-scale,scale):
                        q=[x+d*z for x,z in zip(p,n)];c=BRepClass3d_SolidClassifier(solid,gp_Pnt(*q),1e-7)
                        states.append(dict(signed_outward_offset_mm=d,point_mm=q,inside=c.State()==TopAbs_IN))
                    scale_samples.append(dict(face_index_1based=item['face_index_1based'],u_fraction=uf,v_fraction=vf,
                                              point_mm=p,outward_normal=n,probe_scale_mm=scale,
                                              oriented_principal_curvatures_mm_inverse=[sign*props.MinCurvature(),sign*props.MaxCurvature()],
                                              probes=states,passed=states[0]['inside'] and not states[1]['inside']))
    shoulder_samples=[]
    for scale in (.05,.25,1.):
        for y in (-12.,-30.,-48.):
            probes=[]
            for dx,dz in [(-scale,-scale),(-scale,scale),(scale,-scale),(scale,scale)]:
                p=[50+dx,y,dz];c=BRepClass3d_SolidClassifier(solid,gp_Pnt(*p),1e-7)
                probes.append(dict(point_mm=p,inside=c.State()==TopAbs_IN))
            shoulder_samples.append(dict(station_y_mm=y,probe_scale_mm=scale,probes=probes,
                                         occupied_quadrants=sum(p['inside'] for p in probes),passed=[p['inside'] for p in probes]==[True,False,False,False]))
    report=dict(schema='case11.visible-transition-material-audit.v1',input_brep=str(out/'before.brep'),
        input_sha256=__import__('hashlib').sha256((out/'before.brep').read_bytes()).hexdigest(),cylinders=rows,
        visible_outer_transition=visible,probe_scales_mm=[.05,.25,1.],visible_transition_samples=scale_samples,
        shoulder_multiscale_samples=shoulder_samples,
        passed=len(visible)==1 and all(r['passed'] for r in scale_samples+shoulder_samples),
        interpretation='Visible existing curved band has radial outward material normal and material inward; it is convex independently of camera. Its underside remains concave as expected for a thin curved band.',
        curvature_convention='OCP BRepLProp signed principal curvatures adjusted for actual face orientation; convex radial outward cylinder is negative nonzero curvature.')
    (out/'visible-transition-audit.json').write_text(json.dumps(report,indent=2))
    before=json.loads((out/'report.json').read_text());before['visible_transition_audit']=report
    from OCP.STEPControl import STEPControl_Reader
    before['before']['step']['readback_manifold_audit']=None
    for location,row in [(out/'before.step',before['before'])]+[(out/('r'+str(int(a['radius_mm'])))/'result.step',a) for a in before['attempts'] if 'step' in a]:
        reader=STEPControl_Reader();reader.ReadFile(str(location));reader.TransferRoots()
        row['step']['readback_manifold_audit']=build.manifold_audit(reader.OneShape())
    if before['revision']=='candidate-v5':
        before['remaining_shape_differences']=['A small white triangular opening remains behind the tongue end face in this projection; the source does not clearly show it. A hidden wall would be another material inference.',
            'Exact dimensions, material depth and hidden connections remain inferred; user shape acceptance is pending.']
        before['assumptions'].extend(['The A/T visible junction is a coplanar face partition, not a material step.',
            'The left opening front y=-55 and B front y=-48.5 were adjusted from source silhouette landmarks; target endpoints and material side stayed fixed.'])
    if before['revision']=='candidate-v6':
        before['remaining_shape_differences']=['The inferred A front web closes the prior projected white triangle with real material; its hidden extent is not dimensioned by the PDF.',
            'Exact dimensions, material depth and hidden connections remain inferred; user shape acceptance is pending.']
        before['assumptions'].extend(['The A/T visible junction is a coplanar face partition, not a material step.',
            'The left opening front y=-55 and B front y=-48.5 were adjusted from source silhouette landmarks; target endpoints and material side stayed fixed.',
            'An inferred front web x33.5..47,y-34.5..-31,z-33.35..0 closes the projected white wedge behind the tongue by real material.'])
    before['assumptions']=list(dict.fromkeys(before['assumptions']))
    (out/'report.json').write_text(json.dumps(before,indent=2))
    print(json.dumps(dict(passed=report['passed'],visible=[{k:r[k] for k in ['face_index_1based','point_mm','outward_normal_dot_radial','oriented_principal_curvatures_mm_inverse','material_probes']} for r in visible])))


if __name__=='__main__':main()
