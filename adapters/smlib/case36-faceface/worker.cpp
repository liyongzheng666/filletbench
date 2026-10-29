// Fresh surface-surface calls on two admitted, original finite NURBS faces.
// Reuse the existing read-only geometry/mesh helpers without altering that runner.
#define main filletbench_selected_edge_main_not_called
#include "../native_runner.cpp"
#undef main
#include <SmFilletExecutive.h>
#include <SmAssertArray.h>

static void check(SmStatus status,const char* label) {
    if(status!=SM_SUCCESS)throw std::runtime_error(std::string(label)+" status="+std::to_string(status));
}

static SmFace* one_face(SmBrep* body) {
    SmTArray<SmFace*> faces;
    body->GetFaces(faces);
    if (faces.GetSize() != 1) throw std::runtime_error("Expected one preserved finite face per component");
    return faces[0];
}

static Json support_record(SmFace* face) {
    Json out = Json::object(), corners = Json::array(), vertices = Json::array();
    auto* surface = face->GetSurface();
    auto domain = surface->GetNaturalUVDomain();
    out["natural_uv_domain"] = arr({domain.GetUMin(), domain.GetUMax(), domain.GetVMin(), domain.GetVMax()});
    auto finite = face->GetUVDomain();
    out["face_uv_domain"] = arr({finite.GetUMin(), finite.GetUMax(), finite.GetVMin(), finite.GetVMax()});
    SmVector3d normal;
    check(surface->EvaluateNormal(domain.GetMid(), TRUE, TRUE, normal), "input support normal");
    out["normal"] = xyz(normal);
    for (double u : {domain.GetUMin(), domain.GetUMax()}) {
        for (double v : {domain.GetVMin(), domain.GetVMax()}) {
            SmPoint3d point;
            SmVector3d du, dv;
            check(surface->Evaluate1stDerivatives(SmPoint2d(u, v), TRUE, TRUE, point, du, dv), "input support corner");
            corners.push(xyz(point));
        }
    }
    SmTArray<SmVertex*> actual;
    face->GetVertices(actual);
    for (long i = 0; i < actual.GetSize(); ++i) vertices.push(xyz(actual[i]->GetPoint()));
    out["support_corners_mm"] = corners;
    out["finite_face_vertices_mm"] = vertices;
    return out;
}

static bool original_finite_gate(SmBrep* body, bool left, Json& evidence) {
    SmTArray<SmFace*> faces;
    SmTArray<SmEdge*> edges;
    SmTArray<SmVertex*> vertices;
    body->GetFaces(faces); body->GetEdges(edges); body->GetVertices(vertices);
    std::vector<P> expected;
    if (left) expected = {P(-7,0,5),P(7,0,5),P(-7,0,25),P(7,0,25)};
    else expected = {P(-12.5,5,0),P(12.5,5,0),P(-12.5,23,0),P(12.5,23,0)};
    double maximum = 0;
    for (const auto& wanted : expected) {
        double minimum = 1e100;
        for (long i = 0; i < vertices.GetSize(); ++i) minimum = std::min(minimum, dist(wanted, vertices[i]->GetPoint()));
        maximum = std::max(maximum, minimum);
    }
    double area = 0, volume = 0;
    SmTArray<V> moments;
    SmExtent3d box;
    auto* face = one_face(body);
    check(face->CalculateTightBoundingBox(box), "finite input bounds");
    check(face->ComputePreciseProperties(SM_OT_SAME,1e-9,box.GetMid(),left?280.:450.,0.,area,volume,moments), "finite input area");
    evidence = support_record(face);
    evidence["area_mm2"] = std::abs(area);
    evidence["corner_set_error_mm"] = maximum;
    evidence["bbox_mm"] = arr({box.GetMin().x,box.GetMin().y,box.GetMin().z,box.GetMax().x,box.GetMax().y,box.GetMax().z});
    bool passed = faces.GetSize()==1 && edges.GetSize()==4 && vertices.GetSize()==4 && maximum<=1e-6
        && std::abs(std::abs(area)-(left?280.:450.))<=1e-6 && body->AssertValid(nullptr,SM_LEVEL_2,SM_WALK);
    evidence["passed"] = passed;
    return passed;
}

static double offset_radius(SmFace* face, const V& desired) {
    auto domain = face->GetSurface()->GetNaturalUVDomain();
    V normal;
    check(face->GetSurface()->EvaluateNormal(domain.GetMid(),TRUE,TRUE,normal), "offset direction normal");
    double cosine = dot(unit(normal),desired);
    if (std::abs(cosine)<.999999) throw std::runtime_error("Imported support normal inconsistent with requested contact quadrant");
    return cosine>0 ? 8. : -8.;
}

static Json dense_edges(SmBrep* body) {
    Json out=Json::object(), array=Json::array();
    SmTArray<SmEdge*> edges; body->GetEdges(edges);
    for(long i=0;i<edges.GetSize();++i) {
        Json edge=Json::object(); edge["edge_id"]=i;
        edge["parameter_range"]=arr({edges[i]->GetInterval().GetMin(),edges[i]->GetInterval().GetMax()});
        edge["points"]=pointarray(edgepoints(edges[i],129)); array.push(edge);
    }
    out["edges"]=array; out["method"]="Native actual finite edge EvaluatePoint, 129 samples per edge";
    return out;
}

static Json d2_samples(SmBrep* body) {
    Json out=Json::object(), faces=Json::array(); SmTArray<SmFace*> actual;body->GetFaces(actual);
    for(long i=0;i<actual.GetSize();++i) {
        Json record=Json::object(), samples=Json::array(); auto domain=actual[i]->GetUVDomain();
        record["face_id"]=i; record["surface_type"]=surface_type(actual[i]->GetSurface());
        record["uv_bounding_rectangle"]=arr({domain.GetUMin(),domain.GetUMax(),domain.GetVMin(),domain.GetVMax()});
        for(double u:{.01,.1,.25,.5,.75,.9,.99}) for(double v:{.01,.1,.25,.5,.75,.9,.99}) {
            SmPoint2d uv(domain.GetUMin()+(domain.GetUMax()-domain.GetUMin())*u,
                         domain.GetVMin()+(domain.GetVMax()-domain.GetVMin())*v);
            Json sample=surface_eval(actual[i],uv); SmPoint3d point;V du,dv;
            auto st=actual[i]->GetSurface()->Evaluate1stDerivatives(uv,TRUE,TRUE,point,du,dv);
            SmPoint3d closest;double gap=1e100;auto finite_status=st==SM_SUCCESS?SmApiFaceClosestPoint(actual[i],point,closest,gap):st;
            sample["finite_face_closest_status"]=int(finite_status);sample["finite_face_gap_mm"]=gap;
            sample["finite_face_membership_verified"]=finite_status==SM_SUCCESS&&gap<=1e-6;
            samples.push(sample);
        }
        record["samples"]=samples; faces.push(record);
    }
    out["method"]="Native SmSurface::Evaluate2ndDerivatives on readback surfaces; raw derivatives and principal curvatures";
    out["faces"]=faces; return out;
}

static Json contact_check(SmBrep* result,SmFace* left,SmFace* right) {
    Json out=Json::object(), rails=Json::array(); SmTArray<SmEdge*> edges;result->GetEdges(edges);
    for(long i=0;i<edges.GetSize();++i) {
        auto points=edgepoints(edges[i],65);
        double max_y=0,max_z=0;
        for(auto& p:points){max_y=std::max(max_y,std::abs(p.y));max_z=std::max(max_z,std::abs(p.z));}
        int side=max_y<=1e-6?0:max_z<=1e-6?1:-1; if(side<0)continue;
        SmFace* original=side==0?left:right;V support_normal=side==0?V(0,1,0):V(0,0,1);
        Json rail=Json::object(), samples=Json::array();rail["edge_id"]=i;
        rail["side"]=side==0?"left":"right";rail["support"]=side==0?"y=0":"z=0";
        SmTArray<SmFace*> owners;edges[i]->GetFaces(owners);
        for(auto& point:points) {
            Json sample=Json::object();sample["point"]=xyz(point);SmPoint3d closest;double gap=1e100;
            auto finite_status=SmApiFaceClosestPoint(original,point,closest,gap);
            sample["finite_face_status"]=int(finite_status);sample["finite_face_gap_mm"]=gap;
            sample["finite_face_closest_point"]=xyz(closest);
            sample["contact_coordinate_error_mm"]=std::abs((side==0?point.z:point.y)-8.);
            if(owners.GetSize()) {
                SmTArray<SmPoint2d> uvs;double surface_gap=1e100;SmPoint3d surface_point;
                auto status=SmApiSurfaceClosestPoint(owners[0]->GetSurface(),point,surface_point,uvs,surface_gap);
                sample["result_surface_status"]=int(status);sample["surface_edge_gap_mm"]=surface_gap;
                if(status==SM_SUCCESS&&uvs.GetSize()) {
                    auto evaluation=surface_eval(owners[0],uvs[0]);sample["actual_surface_D2"]=evaluation;
                    V normal;check(owners[0]->GetSurface()->EvaluateNormal(uvs[0],TRUE,TRUE,normal),"readback rail normal");
                    sample["normal"]=xyz(normal);
                    sample["tangent_plane_angle_deg"]=std::acos(std::min(1.,std::abs(dot(unit(normal),support_normal))))*180./M_PI;
                }
            }
            samples.push(sample);
        }
        rail["samples"]=samples; rails.push(rail);
    }
    out["rails"]=rails;out["method"]="Readback finite edge to original finite face; actual result surface closest UV and normal/D2";
    return out;
}

static void validity_details(SmBrep* body,const std::string& name) {
    SmAssertArray reports;bool valid=body->AssertValid(&reports,SM_LEVEL_2,SM_WALK);Json out=Json::object(), failures=Json::array();
    for(long i=0;i<reports.GetSize();++i)if(!reports[i]->m_bOK){Json f=Json::object();auto* r=reports[i];
        f["name"]=r->m_pName?r->m_pName:"";f["message"]=r->m_pMessage?r->m_pMessage:"";
        f["owner_type"]=r->m_sOwnerTypeString?r->m_sOwnerTypeString:"";f["test_index"]=long(r->m_lTestIndex);
        f["distance_mm"]=r->m_dDist3d;failures.push(f);}
    out["valid"]=valid;out["failed_reports"]=failures;save(name,out);
}

static void snapshot(SmBrep* body,const std::string& name,const Config& cfg,bool with_mesh) {
    check(persist(body,name+".smb"),"save native geometry without conversion");
    save(name+".json",inspect(body,cfg));save(name+"-edges.json",dense_edges(body));
    if(with_mesh)save(name+".mesh.json",tessellate(body));
}

static Json post_domain_side(SmBrep* body,bool left) {
    Json out=Json::object(),coverage=Json::array();double coverage_max=0,boundary_max=0;
    bool queries_ok=true;long boundary_count=0;
    for(int i=0;i<=16;++i)for(int j=0;j<=16;++j) {
        P expected=left?P(-7.+14.*i/16.,0.,5.+20.*j/16.):P(-12.5+25.*i/16.,5.+18.*j/16.,0.);
        P closest;double gap=1e100;auto status=SmApiGetClosestPoint(body,expected,closest,gap);
        queries_ok=queries_ok&&status==SM_SUCCESS;coverage_max=std::max(coverage_max,gap);
        Json point=Json::object();point["original_point_mm"]=xyz(expected);point["post_closest_point_mm"]=xyz(closest);
        point["status"]=int(status);point["distance_mm"]=gap;coverage.push(point);
    }
    SmTArray<SmEdge*> edges;body->GetEdges(edges);
    for(long i=0;i<edges.GetSize();++i)for(const auto& p:edgepoints(edges[i],129)) {
        double outside=left?std::max({std::abs(p.y),-7.-p.x,p.x-7.,5.-p.z,p.z-25.,0.}):
                            std::max({std::abs(p.z),-12.5-p.x,p.x-12.5,5.-p.y,p.y-23.,0.});
        boundary_max=std::max(boundary_max,outside);++boundary_count;
    }
    Config cfg;cfg.kind="sheet";auto measurements=inspect(body,cfg);auto statistics=std::get<Json::Obj>(measurements.v).at("native_stats");
    double expected_area=left?280.:450.,area_error=std::abs(jd(statistics,"area",1e100)-expected_area);
    P minimum,maximum;check(SmApiBrepBoundingBox(body,TRUE,minimum,maximum),"post domain bbox");
    P target_min=left?P(-7,0,5):P(-12.5,5,0),target_max=left?P(7,0,25):P(12.5,23,0);
    double bounds_error=std::max(dist(minimum,target_min),dist(maximum,target_max));
    out["native_stats"]=statistics;out["original_grid_samples"]=coverage;
    out["original_to_post_max_gap_mm"]=coverage_max;out["post_boundary_to_original_mask_max_violation_mm"]=boundary_max;
    out["post_boundary_samples"]=boundary_count;out["area_error_mm2"]=area_error;out["bbox_corner_error_mm"]=bounds_error;
    out["passed"]=queries_ok&&coverage_max<=1e-6&&boundary_max<=1e-6&&area_error<=1e-6&&bounds_error<=1e-6&&jb(statistics,"valid");
    out["scope"]="Native global area/bbox plus 17x17 original finite-rectangle coverage and dense actual post-boundary containment; sampled coverage, not a global analytic partition proof";
    return out;
}

int main(int argc,char** argv) {
    if(argc==5&&std::string(argv[1])=="--audit-post") {
        run_dir=argv[4];try{SmApiCreateContext();auto* context=SmApiGetOrCreateContext();
            std::unique_ptr<SmBrep> left(new(*context)SmBrep()),right(new(*context)SmBrep());
            check(left->ReadFromFile(*context,argv[2],SM_ASCII,FALSE),"audit read post left");
            check(right->ReadFromFile(*context,argv[3],SM_ASCII,FALSE),"audit read post right");
            Json audit=Json::object();audit["left"]=post_domain_side(left.get(),true);audit["right"]=post_domain_side(right.get(),false);
            audit["query_only"]=true;audit["native_fillet_called"]=false;save("post-domain-audit.json",audit);return 0;
        }catch(const std::exception& error){std::cerr<<error.what()<<std::endl;return 1;}
    }
    if(argc!=6){std::cerr<<"usage worker LEFT.smb RIGHT.smb TRIM BASE_TRIM OUTDIR\n";return 2;}
    run_dir=argv[5];int trim=std::stoi(argv[3]),base=std::stoi(argv[4]);
    Config cfg;cfg.kind="sheet";cfg.radius=8;
    try {
        if(trim<0||trim>3||base<0||base>2)throw std::runtime_error("Unsupported declared trim request");
        phase("read_exact_admitted_components");SmApiCreateContext();auto* context=SmApiGetOrCreateContext();
        std::unique_ptr<SmBrep> raw_left(new(*context)SmBrep()),raw_right(new(*context)SmBrep());
        check(raw_left->ReadFromFile(*context,argv[1],SM_ASCII,FALSE),"read exact left without rebuild/heal");
        check(raw_right->ReadFromFile(*context,argv[2],SM_ASCII,FALSE),"read exact right without rebuild/heal");
        check(persist(raw_left.get(),"source-left-before.smb"),"save source left");check(persist(raw_right.get(),"source-right-before.smb"),"save source right");
        std::unique_ptr<SmBrep> left(new(*context)SmBrep(*raw_left)),right(new(*context)SmBrep(*raw_right));
        phase("measure_original_finite_input");Json lg,rg,gates=Json::object();
        bool lp=original_finite_gate(left.get(),true,lg),rp=original_finite_gate(right.get(),false,rg);double gap=1e100;
        auto gap_status=SmApiBrepDistance(left.get(),right.get(),gap);
        gates["left"]=lg;gates["right"]=rg;gates["gap_status"]=int(gap_status);gates["finite_face_gap_mm"]=gap;
        bool passed=lp&&rp&&gap_status==SM_SUCCESS&&std::abs(gap-std::sqrt(50.))<=1e-6;
        gates["passed"]=passed;save("input-gates.json",gates);
        save("input-left-support.json",lg);save("input-right-support.json",rg);
        snapshot(left.get(),"input-left",cfg,true);snapshot(right.get(),"input-right",cfg,true);
        if(!passed)throw std::runtime_error("Original finite domain admission failed; fillet not called");
        double lr=offset_radius(one_face(left.get()),V(0,1,0)),rr=offset_radius(one_face(right.get()),V(0,0,1));
        Json request=Json::object();request["api"]="SmFilletExecutive::SurfaceSurfaceFillet";
        request["radius_mm"]=8.;request["signed_radius_left"]=lr;request["signed_radius_right"]=rr;
        request["trim_enum"]=trim;request["base_trim"]=base;request["cross_section_enum"]=2;
        request["cross_section_meaning"]="exact rational circular";request["solver_contact_tolerance_mm"]=1e-6;
        request["approximation_accuracy_parameter"]=.001;request["approximation_enabled"]=false;
        request["explicit_post_crop"]=false;request["automatic_heal"]=false;request["stitch"]=false;
        request["readback_rebuild_UV_trim_curves"]=false;save("request.json",request);
        phase("native_surface_surface_call");SmBrep* result=nullptr;SmFilletExecutive executive(*context);
        auto started=std::chrono::steady_clock::now();auto status=executive.SurfaceSurfaceFillet(*context,
            one_face(left.get())->GetSurface(),one_face(right.get())->GetSurface(),lr,rr,1e-6,result,
            2,.001,static_cast<SmBoundaryTrimmingType>(trim),base,FALSE,FALSE);
        Json operation=Json::object();operation["native_call_started"]=true;operation["native_api_raw_status"]=int(status);
        operation["native_api_success"]=status==SM_SUCCESS;operation["nonnull_result"]=result!=nullptr;
        operation["operation_ms"]=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-started).count();save("operation.json",operation);
        phase("save_post_inputs_without_repair");snapshot(left.get(),"post-left",cfg,false);snapshot(right.get(),"post-right",cfg,false);
        Json post_domains=Json::object();post_domains["left"]=post_domain_side(left.get(),true);post_domains["right"]=post_domain_side(right.get(),false);
        post_domains["query_only"]=true;save("post-domain-audit.json",post_domains);
        check(persist(raw_left.get(),"source-left-after.smb"),"save unchanged source left");check(persist(raw_right.get(),"source-right-after.smb"),"save unchanged source right");
        if(!result){phase("native_returned_no_patch");return status==SM_SUCCESS?3:4;}
        phase("save_raw_native_result");snapshot(result,"native",cfg,false);validity_details(result,"native-validity.json");
        phase("native_readback_without_rebuild");std::unique_ptr<SmBrep> readback(new(*context)SmBrep());
        auto read_status=readback->ReadFromFile(*context,(run_dir+"/native.smb").c_str(),SM_ASCII,FALSE);
        Json read=Json::object();read["status"]=int(read_status);read["rebuild_UV_trim_curves"]=false;save("readback-operation.json",read);
        check(read_status,"native SMB readback");snapshot(readback.get(),"readback",cfg,false);validity_details(readback.get(),"readback-validity.json");
        phase("readback_surface_and_contact_measurements");save("surface-D2.json",d2_samples(readback.get()));
        save("contact-check.json",contact_check(readback.get(),one_face(raw_left.get()),one_face(raw_right.get())));
        phase("mesh_on_native_copy_with_CAD_face_ids");save("result.mesh.json",tessellate(readback.get()));
        phase("complete");return status==SM_SUCCESS?0:4;
    } catch(const std::exception& error) {
        Json failure=Json::object();failure["error"]=error.what();save("error.json",failure);
        std::cerr<<error.what()<<std::endl;return 1;
    }
}
