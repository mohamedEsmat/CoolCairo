using UnityEngine;

namespace CoolCairo
{
    // Procedural starfield on a large sphere around this object: one mesh of small quads, with
    // random brightness and a slight colour tint, denser along a faint galactic band.
    // Used behind the globe (radius 40) and behind the district (radius in metres).
    // Decorative only; fixed seed so the sky looks the same every launch.
    [RequireComponent(typeof(MeshFilter), typeof(MeshRenderer))]
    public class StarField : MonoBehaviour
    {
        const int StarCount = 9000;
        const int Seed = 813;
        const float ReferenceRadius = 40f; // Star sizes below are tuned for this radius.

        [SerializeField] Material material;  // CoolCairo/VertexColorUnlit
        [SerializeField] float radius = ReferenceRadius;

        void Awake()
        {
            GetComponent<MeshRenderer>().sharedMaterial = material;
            GetComponent<MeshFilter>().sharedMesh = BuildMesh(radius);
        }

        static Mesh BuildMesh(float radius)
        {
            var rng = new System.Random(Seed);
            float Rand() => (float)rng.NextDouble();
            float scale = radius / ReferenceRadius;

            var verts = new Vector3[StarCount * 4];
            var colors = new Color32[StarCount * 4];
            var tris = new int[StarCount * 12];
            // Tilted plane of the "galactic" band.
            var bandNormal = Quaternion.Euler(62f, 0f, 20f) * Vector3.up;

            for (int s = 0; s < StarCount; s++)
            {
                Vector3 dir;
                do
                {
                    dir = new Vector3(Rand() * 2f - 1f, Rand() * 2f - 1f, Rand() * 2f - 1f);
                } while (dir.sqrMagnitude > 1f || dir.sqrMagnitude < 1e-4f);
                dir.Normalize();
                // A third of the stars cluster near the band for a Milky Way impression.
                if (s % 3 == 0)
                    dir = (dir - bandNormal * Vector3.Dot(dir, bandNormal) * (0.85f + 0.1f * Rand())).normalized;

                // Brightness: mostly faint, a few bright ones (power law).
                float b = Mathf.Pow(Rand(), 3.5f);
                float size = Mathf.Lerp(0.018f, 0.07f, b) * scale; // Small: large quads read as squares.
                float tint = Rand();
                var baseCol = tint < 0.15f ? new Color(0.88f, 0.93f, 1f)   // faint blue-white
                            : tint > 0.9f ? new Color(1f, 0.95f, 0.88f)    // faint warm
                            : Color.white;
                Color32 c = baseCol * Mathf.Lerp(0.25f, 1f, b);

                // Quad perpendicular to the view from the centre.
                var centre = dir * radius;
                var right = Vector3.Cross(dir, Mathf.Abs(dir.y) < 0.99f ? Vector3.up : Vector3.right).normalized * size;
                var up = Vector3.Cross(right, dir).normalized * size;
                int v = s * 4;
                verts[v] = centre - right - up;
                verts[v + 1] = centre - right + up;
                verts[v + 2] = centre + right + up;
                verts[v + 3] = centre + right - up;
                for (int k = 0; k < 4; k++) colors[v + k] = c;
                int t = s * 12;
                // Both windings, so each star is visible whichever way the quad ends up facing.
                tris[t] = v; tris[t + 1] = v + 1; tris[t + 2] = v + 2;
                tris[t + 3] = v; tris[t + 4] = v + 2; tris[t + 5] = v + 3;
                tris[t + 6] = v; tris[t + 7] = v + 2; tris[t + 8] = v + 1;
                tris[t + 9] = v; tris[t + 10] = v + 3; tris[t + 11] = v + 2;
            }

            var mesh = new Mesh { name = "Stars", indexFormat = UnityEngine.Rendering.IndexFormat.UInt32 };
            mesh.vertices = verts;
            mesh.colors32 = colors;
            mesh.triangles = tris;
            mesh.bounds = new Bounds(Vector3.zero, Vector3.one * radius * 2.2f);
            return mesh;
        }
    }
}
