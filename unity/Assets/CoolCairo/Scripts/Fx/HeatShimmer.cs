using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using UnityEngine.Rendering;

namespace CoolCairo
{
    // Hot air rising over the hottest tenth of today's blocks, in the heat and heat-risk views:
    // one soft camera-facing plume per block (Glow shader). Plumes follow the live model: cool a
    // hot block below the line and its shimmer goes away.
    public class HeatShimmer : MonoBehaviour
    {
        [SerializeField] DistrictView district;
        [SerializeField] Material material;   // CoolCairo/Glow
        [SerializeField, Range(0.5f, 0.99f)] float hottestShare = 0.9f;   // percentile of today's blocks
        [SerializeField] float plumeHeight = 60f;                          // metres above the roofs

        static readonly Color Haze = new Color(1f, 0.5f, 0.18f);

        Mesh _mesh;
        MeshRenderer _renderer;
        float _threshold, _top;
        bool _dirty = true;
        ViewMode _shownMode = (ViewMode)(-1);

        public int HotBlocks { get; private set; }   // blocks with a plume now (self-test)
        public float Threshold => _threshold;

        void Start()
        {
            var go = new GameObject("HeatShimmer", typeof(MeshFilter), typeof(MeshRenderer));
            go.transform.SetParent(transform, false);
            _renderer = go.GetComponent<MeshRenderer>();
            _renderer.sharedMaterial = material;
            _renderer.shadowCastingMode = ShadowCastingMode.Off;
            _renderer.receiveShadows = false;
            _mesh = new Mesh { name = "HeatShimmer" };
            go.GetComponent<MeshFilter>().sharedMesh = _mesh;

            var model = district.Model;
            var today = Enumerable.Range(0, district.Data.BlockCount).Where(model.IsValid)
                                  .Select(model.BaselineLst).OrderBy(t => t).ToArray();
            _threshold = today[Mathf.Clamp(Mathf.FloorToInt(hottestShare * today.Length), 0, today.Length - 1)];
            _top = today[today.Length - 1];
            model.Changed += MarkDirty;
        }

        void OnDestroy()
        {
            if (district != null && district.Model != null) district.Model.Changed -= MarkDirty;
        }

        void MarkDirty() => _dirty = true;

        void Update()
        {
            bool show = district.Mode == ViewMode.Heat || district.Mode == ViewMode.Risk;
            if (district.Mode != _shownMode) { _shownMode = district.Mode; _renderer.enabled = show; }
            if (show && _dirty) Rebuild();
        }

        void Rebuild()
        {
            _dirty = false;
            var d = district.Data;
            var model = district.Model;
            var verts = new List<Vector3>();
            var colors = new List<Color>();
            var uvs = new List<Vector2>();
            var plumes = new List<Vector2>();
            var tris = new List<int>();
            float half = d.blockSize * 0.5f;
            HotBlocks = 0;
            for (int b = 0; b < d.BlockCount; b++)
            {
                if (!model.IsValid(b)) continue;
                float lst = model.Lst(b);
                if (lst < _threshold) continue;
                HotBlocks++;
                float heat = Mathf.InverseLerp(_threshold, _top, lst);
                var c = Haze;
                c.a = Mathf.Lerp(0.06f, 0.18f, heat);
                float top = Mathf.Max(0f, d.blocks.meanHeightM[b]) + plumeHeight * Mathf.Lerp(0.7f, 1.2f, heat);
                int v = verts.Count;
                // Four corners at the block centre; the shader spreads them to face the camera.
                var corners = new[] { new Vector2(-1, 0), new Vector2(-1, 1), new Vector2(1, 1), new Vector2(1, 0) };
                foreach (var k in corners)
                {
                    verts.Add(d.BlockCentre(b));
                    colors.Add(c);
                    uvs.Add(new Vector2(1f, k.y));
                    plumes.Add(new Vector2(k.x * half, top));
                }
                tris.AddRange(new[] { v, v + 1, v + 2, v, v + 2, v + 3 });
            }
            _mesh.Clear();
            _mesh.SetVertices(verts);
            _mesh.SetColors(colors);
            _mesh.SetUVs(0, uvs);
            _mesh.SetUVs(1, plumes);
            _mesh.SetTriangles(tris, 0);
            // The vertices all sit on the ground; give culling the plumes' real extent.
            float w = d.cols * d.blockSize, depth = d.rows * d.blockSize;
            _mesh.bounds = new Bounds(new Vector3(w / 2f, 100f, depth / 2f), new Vector3(w + 200f, 300f, depth + 200f));
        }
    }
}
