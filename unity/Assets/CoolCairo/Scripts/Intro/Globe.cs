using UnityEngine;

namespace CoolCairo
{
    // Unit-radius Earth at the origin. The mesh is generated here (not Unity's sphere primitive)
    // so texture coordinates match latitude/longitude exactly and markers land in the right place.
    // Convention: +Y = north pole, lon 0 faces -Z, east is to the right when viewed from outside.
    [RequireComponent(typeof(MeshFilter), typeof(MeshRenderer))]
    public class Globe : MonoBehaviour
    {
        const int LatSegments = 128, LonSegments = 256;

        public static Vector3 LatLonToPosition(float latDeg, float lonDeg, float radius = 1f)
        {
            float lat = latDeg * Mathf.Deg2Rad, lon = lonDeg * Mathf.Deg2Rad;
            return new Vector3(Mathf.Cos(lat) * Mathf.Sin(lon), Mathf.Sin(lat), -Mathf.Cos(lat) * Mathf.Cos(lon)) * radius;
        }

        void Awake() => GetComponent<MeshFilter>().sharedMesh = BuildMesh();

        static Mesh BuildMesh()
        {
            int cols = LonSegments + 1, rows = LatSegments + 1;
            var verts = new Vector3[rows * cols];
            var normals = new Vector3[verts.Length];
            var uvs = new Vector2[verts.Length];
            for (int i = 0; i < rows; i++)
            for (int j = 0; j < cols; j++)
            {
                float lat = -90f + 180f * i / LatSegments;
                float lon = -180f + 360f * j / LonSegments;
                int v = i * cols + j;
                verts[v] = LatLonToPosition(lat, lon);
                normals[v] = verts[v];
                uvs[v] = new Vector2((float)j / LonSegments, (float)i / LatSegments);
            }

            // Seen from outside, +lon is right and +lat is up, so (bottom-left, top-left, top-right)
            // is clockwise: Unity's front face.
            var tris = new int[LatSegments * LonSegments * 6];
            int t = 0;
            for (int i = 0; i < LatSegments; i++)
            for (int j = 0; j < LonSegments; j++)
            {
                int a = i * cols + j, b = a + 1, d = a + cols, c = d + 1;
                tris[t++] = a; tris[t++] = d; tris[t++] = c;
                tris[t++] = a; tris[t++] = c; tris[t++] = b;
            }

            var mesh = new Mesh { name = "Earth" };
            mesh.vertices = verts;
            mesh.normals = normals;
            mesh.uv = uvs;
            mesh.triangles = tris;
            mesh.RecalculateBounds();
            return mesh;
        }
    }
}
