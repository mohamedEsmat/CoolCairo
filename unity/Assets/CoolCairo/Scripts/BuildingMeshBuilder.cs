using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;

namespace CoolCairo
{
    // Extrudes every footprint into one combined mesh (one draw call for the whole district).
    // Remembers each building's roof and wall vertex ranges so colours can be updated in place.
    public class BuildingMesh
    {
        public Mesh Mesh;
        public int[] RoofStart, RoofCount, WallStart, WallCount;
        public Color32[] Colors;
    }

    public static class BuildingMeshBuilder
    {
        public static BuildingMesh Build(BuildingArrays b)
        {
            var verts = new List<Vector3>(b.xz.Length * 3);
            var normals = new List<Vector3>(b.xz.Length * 3);
            var tris = new List<int>(b.xz.Length * 6);
            var result = new BuildingMesh
            {
                RoofStart = new int[b.count], RoofCount = new int[b.count],
                WallStart = new int[b.count], WallCount = new int[b.count],
            };
            var ring = new List<Vector2>();
            var roofTris = new List<int>();

            for (int i = 0; i < b.count; i++)
            {
                ring.Clear();
                int s = b.vertexStart[i];
                for (int k = 0; k < b.vertexCount[i]; k++)
                    ring.Add(new Vector2(b.xz[2 * (s + k)], b.xz[2 * (s + k) + 1]));
                float h = b.heightM[i];

                // Roof: ear-clipped footprint at height h. Rings are CCW in (x, z) seen from above;
                // Unity front faces are clockwise, so each triangle is reversed.
                result.RoofStart[i] = verts.Count;
                roofTris.Clear();
                Triangulator.Triangulate(ring, roofTris);
                int roofBase = verts.Count;
                foreach (var p in ring)
                {
                    verts.Add(new Vector3(p.x, h, p.y));
                    normals.Add(Vector3.up);
                }
                for (int t = 0; t < roofTris.Count; t += 3)
                {
                    tris.Add(roofBase + roofTris[t]);
                    tris.Add(roofBase + roofTris[t + 2]);
                    tris.Add(roofBase + roofTris[t + 1]);
                }
                result.RoofCount[i] = verts.Count - result.RoofStart[i];

                // Walls: one flat-shaded quad per edge.
                result.WallStart[i] = verts.Count;
                for (int k = 0; k < ring.Count; k++)
                {
                    Vector2 a = ring[k], c = ring[(k + 1) % ring.Count];
                    var normal = new Vector3(c.y - a.y, 0f, -(c.x - a.x)).normalized;
                    int v = verts.Count;
                    verts.Add(new Vector3(a.x, 0f, a.y));
                    verts.Add(new Vector3(a.x, h, a.y));
                    verts.Add(new Vector3(c.x, h, c.y));
                    verts.Add(new Vector3(c.x, 0f, c.y));
                    for (int n = 0; n < 4; n++) normals.Add(normal);
                    tris.Add(v); tris.Add(v + 1); tris.Add(v + 2);
                    tris.Add(v); tris.Add(v + 2); tris.Add(v + 3);
                }
                result.WallCount[i] = verts.Count - result.WallStart[i];
            }

            var mesh = new Mesh { name = "Buildings", indexFormat = IndexFormat.UInt32 };
            mesh.SetVertices(verts);
            mesh.SetNormals(normals);
            mesh.SetTriangles(tris, 0);
            mesh.RecalculateBounds();
            result.Colors = new Color32[verts.Count];
            mesh.SetColors(result.Colors);
            result.Mesh = mesh;
            return result;
        }
    }

    // Ear clipping for simple CCW polygons. O(n^2), fine for building footprints.
    public static class Triangulator
    {
        public static void Triangulate(List<Vector2> poly, List<int> output)
        {
            var idx = new List<int>(poly.Count);
            for (int i = 0; i < poly.Count; i++) idx.Add(i);

            int guard = poly.Count * poly.Count;
            while (idx.Count > 3 && guard-- > 0)
            {
                bool clipped = false;
                for (int i = 0; i < idx.Count; i++)
                {
                    int ip = idx[(i + idx.Count - 1) % idx.Count], ic = idx[i], inx = idx[(i + 1) % idx.Count];
                    Vector2 a = poly[ip], b = poly[ic], c = poly[inx];
                    if (Cross(a, b, c) <= 0f) continue; // Reflex or degenerate corner.
                    bool containsOther = false;
                    foreach (int j in idx)
                    {
                        if (j == ip || j == ic || j == inx) continue;
                        if (InTriangle(poly[j], a, b, c)) { containsOther = true; break; }
                    }
                    if (containsOther) continue;
                    output.Add(ip); output.Add(ic); output.Add(inx);
                    idx.RemoveAt(i);
                    clipped = true;
                    break;
                }
                if (!clipped) break; // Self-intersecting input: fall back to a fan for the rest.
            }
            for (int i = 1; i + 1 < idx.Count; i++)
            {
                output.Add(idx[0]); output.Add(idx[i]); output.Add(idx[i + 1]);
            }
        }

        static float Cross(Vector2 a, Vector2 b, Vector2 c) =>
            (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x);

        static bool InTriangle(Vector2 p, Vector2 a, Vector2 b, Vector2 c) =>
            Cross(a, b, p) >= 0f && Cross(b, c, p) >= 0f && Cross(c, a, p) >= 0f;
    }
}
