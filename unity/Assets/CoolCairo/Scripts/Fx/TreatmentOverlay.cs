using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;

namespace CoolCairo
{
    // Coloured rings around every block a measure has been painted on, in every view, so a plan
    // stays visible even where its temperature change is too small to see in the colours.
    // One ring per measure, nested inside each other; a ring is thicker the larger the share of
    // the block that is treated. Rebuilt only when the plan changes.
    public class TreatmentOverlay : MonoBehaviour
    {
        [SerializeField] DistrictView district;
        [SerializeField] Material material;   // CoolCairo/VertexColorUnlit

        // Same order and colours as the tool dock and the legend key.
        public static readonly (Intervention kind, Color color, string label)[] Measures =
        {
            (Intervention.CoolRoof, new Color(0.66f, 0.93f, 1.00f), "Cool roofs"),        // #A8EEFF
            (Intervention.CoolPavement, new Color(0.25f, 0.62f, 0.85f), "Cool pavements"), // #409ED9
            (Intervention.Trees, new Color(0.30f, 0.82f, 0.54f), "Street trees"),          // #4CD08A
            (Intervention.PocketPark, new Color(0.75f, 0.90f, 0.35f), "Pocket parks"),     // #BFE659
        };

        const float MinWidth = 2.5f, MaxWidth = 7f, Gap = 1.5f;   // metres
        const float Lift = 0.5f;                                   // below the hover outline

        Mesh _mesh;
        bool _dirty = true;

        public int RingCount { get; private set; }   // rings drawn now (self-test)

        void Start()
        {
            var go = new GameObject("TreatmentRings", typeof(MeshFilter), typeof(MeshRenderer));
            go.transform.SetParent(transform, false);
            var r = go.GetComponent<MeshRenderer>();
            r.sharedMaterial = material;
            r.shadowCastingMode = ShadowCastingMode.Off;
            r.receiveShadows = false;
            _mesh = new Mesh { name = "TreatmentRings" };
            _mesh.MarkDynamic();
            go.GetComponent<MeshFilter>().sharedMesh = _mesh;
            district.Model.Changed += MarkDirty;
        }

        void OnDestroy()
        {
            if (district != null && district.Model != null) district.Model.Changed -= MarkDirty;
        }

        void MarkDirty() => _dirty = true;

        void LateUpdate()
        {
            if (!_dirty) return;
            _dirty = false;
            Rebuild();
        }

        void Rebuild()
        {
            var d = district.Data;
            var model = district.Model;
            var verts = new List<Vector3>();
            var colors = new List<Color>();
            var tris = new List<int>();
            RingCount = 0;
            for (int b = 0; b < d.BlockCount; b++)
            {
                float inset = 0f;
                foreach (var (kind, color, _) in Measures)
                {
                    float share = model.Share(kind, b);
                    if (share < 0.01f) continue;
                    float w = Mathf.Lerp(MinWidth, MaxWidth, share);
                    Ring(d, b, inset, w, color, verts, colors, tris);
                    inset += w + Gap;
                    RingCount++;
                }
            }
            _mesh.Clear();
            _mesh.SetVertices(verts);
            _mesh.SetColors(colors);
            _mesh.SetTriangles(tris, 0);
            _mesh.RecalculateBounds();
        }

        // Four strips along the inside of the block's edges, `inset` metres in from the edge.
        static void Ring(DistrictData d, int b, float inset, float w, Color c,
                         List<Vector3> v, List<Color> col, List<int> t)
        {
            float s = d.blockSize;
            float x0 = (b % d.cols) * s + inset, z0 = (b / d.cols) * s + inset;
            float x1 = x0 + s - 2f * inset, z1 = z0 + s - 2f * inset;
            Strip(v, col, t, x0, z0, x1, z0 + w, c);
            Strip(v, col, t, x0, z1 - w, x1, z1, c);
            Strip(v, col, t, x0, z0 + w, x0 + w, z1 - w, c);
            Strip(v, col, t, x1 - w, z0 + w, x1, z1 - w, c);
        }

        static void Strip(List<Vector3> v, List<Color> col, List<int> t,
                          float xa, float za, float xb, float zb, Color c)
        {
            int i = v.Count;
            v.Add(new Vector3(xa, Lift, za));
            v.Add(new Vector3(xa, Lift, zb));
            v.Add(new Vector3(xb, Lift, zb));
            v.Add(new Vector3(xb, Lift, za));
            for (int k = 0; k < 4; k++) col.Add(c);
            t.Add(i); t.Add(i + 1); t.Add(i + 2);
            t.Add(i); t.Add(i + 2); t.Add(i + 3);
        }
    }
}
