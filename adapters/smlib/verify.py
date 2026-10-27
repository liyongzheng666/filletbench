"""Independent rational B-spline sample evaluation, using only Python stdlib."""
import math


def basis(knots, degree, parameter):
    n = len(knots) - degree - 1
    tol = 1e-12 * max(1, abs(knots[-degree - 1] - knots[degree]))
    if abs(parameter - knots[degree]) <= tol:
        return [1.] + [0.] * (n - 1)
    if abs(parameter - knots[-degree - 1]) <= tol:
        return [0.] * (n - 1) + [1.]
    values = [float(a <= parameter < b) for a, b in zip(knots, knots[1:])]
    for q in range(1, degree + 1):
        next_values = []
        for i in range(len(values) - 1):
            a = 0 if knots[i + q] == knots[i] else (parameter - knots[i]) / (knots[i + q] - knots[i]) * values[i]
            b = 0 if knots[i + q + 1] == knots[i + 1] else (knots[i + q + 1] - parameter) / (knots[i + q + 1] - knots[i + 1]) * values[i + 1]
            next_values.append(a + b)
        values = next_values
    return values


def weighted_point(poles, coefficients):
    denominator = sum(coefficients)
    if not math.isfinite(denominator) or abs(denominator) <= 1e-30:
        raise ValueError("nonfinite or zero rational denominator")
    result = [sum(p[j] * a for p, a in zip(poles, coefficients)) / denominator for j in range(3)]
    if not all(math.isfinite(x) for x in result):
        raise ValueError("nonfinite rational evaluation")
    return result


def curve(curve_data, parameter):
    poles = curve_data["poles"]
    coefficients = basis(curve_data["knots"], curve_data["degree"], parameter)
    weights = curve_data.get("weights", [1.] * len(poles))
    return weighted_point(poles, [a * w for a, w in zip(coefficients, weights)])


def surface(surface_data, uv):
    poles = surface_data["poles"]
    nu, nv = len(poles), len(poles[0])
    a = basis(surface_data["knots_u"], surface_data["degree_u"], uv[0])
    b = basis(surface_data["knots_v"], surface_data["degree_v"], uv[1])
    weights = surface_data.get("weights", [[1.] * nv for _ in range(nu)])
    return weighted_point([p for row in poles for p in row],
                          [a[i] * b[j] * weights[i][j] for i in range(nu) for j in range(nv)])


def verify(component, samples, stats, volume):
    edges = {e["id"]: e for e in component["edges"]}
    faces = {f["id"]: f for sh in component["shells"] for f in sh["faces"]}
    edge_errors = [math.dist(curve(edges[e["source_id"]]["curve"], s["parameter"]), s["point"])
                   for e in samples["edges"] for s in e["samples"]]
    face_errors = [math.dist(surface(faces[f["source_id"]]["surface"], s["uv"]), s["point"])
                   for f in samples["faces"] for s in f["samples"]]
    source_errors = [float(e["curve"].get("source_evaluation_error_mm", math.inf)) for e in component["edges"]]
    source_errors += [float(s.get("source_evaluation_error_mm", math.inf))
                      for f in faces.values() for s in f["surface"].get("source_samples", [])]
    expected = component["source_stats"]
    area_error = abs(stats["area_mm2"] - expected["area"])
    volume_error = abs(volume["volume_mm3"] - expected["volume"])
    bbox_error = max(abs(a - b) for a, b in zip(stats["bbox_min"] + stats["bbox_max"], expected["bbox"]))
    checks = dict(area=area_error <= max(1e-5, abs(expected["area"]) * 1e-6),
                  volume=volume_error <= max(1e-5, abs(expected["volume"]) * 1e-6), bbox=bbox_error <= 1e-5,
                  curve_samples=bool(edge_errors) and max(edge_errors) <= 1e-7,
                  surface_samples=bool(face_errors) and max(face_errors) <= 1e-7,
                  upstream_conversion=bool(source_errors) and max(source_errors) <= 1e-7)
    return dict(method="Independent Cox-de Boor rational basis; native sample points and source metrics",
                geometry_is_sampled_not_global_analytic_proof=True, checks=checks,
                passed=all(checks.values()), native_edge_samples=len(edge_errors), native_surface_samples=len(face_errors),
                curve_residual_mm=max(edge_errors, default=None), surface_residual_mm=max(face_errors, default=None),
                upstream_conversion_residual_mm=max(source_errors, default=None),
                area_error_mm2=area_error, volume_error_mm3=volume_error, bbox_error_mm=bbox_error)
