// Smooth tessellation within each CAD face; retain creases between CAD faces.
export function faceLocalMesh(mesh) {
  if (!Array.isArray(mesh.face_ids) || mesh.face_ids.length !== mesh.triangles.length) return mesh;
  const vertices = [], triangles = [], indices = new Map();
  for (let t = 0; t < mesh.triangles.length; t++) {
    const face = mesh.face_ids[t];
    triangles.push(mesh.triangles[t].map((index) => {
      const key = `${face}:${index}`;
      if (!indices.has(key)) { indices.set(key, vertices.length); vertices.push(mesh.vertices[index]); }
      return indices.get(key);
    }));
  }
  return { vertices, triangles };
}
