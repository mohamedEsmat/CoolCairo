using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;

namespace CoolCairo
{
    // Outlines the block under the mouse (white) and every block the brush would paint (orange),
    // so the planner sees where a stroke will land before clicking. Drawn as thin flat strips
    // just above the ground; the meshes are rebuilt only when the hovered block or radius changes.
    public class BlockHighlight : MonoBehaviour
    {
        [SerializeField] DistrictView district;
        [SerializeField] InterventionBrush brush;
        [SerializeField] Material material;   // URP Unlit, both faces; colour set per outline

        const float HoverWidth = 6f, AreaWidth = 3f;   // metres
        const float HoverLift = 0.8f, AreaLift = 0.6f; // above the ground plane, below any roof

        MeshFilter _hover, _area, _focus;
        int _shownBlock = -2, _shownRadius = -1;
        float _focusUntil;

        const float FocusWidth = 9f, FocusLift = 1.0f, FocusSeconds = 4f;

        void Start()
        {
            _area = Outline("BrushArea", HudStyle.Accent);
            _hover = Outline("HoverOutline", Color.white);
            _focus = Outline("FocusOutline", HudStyle.ChromeBright);
        }

        // Marks one block (the block the plan panel just flew to), for a few seconds or until cleared.
        public void Focus(int block, float seconds = FocusSeconds)
        {
            Fill(_focus.sharedMesh, new List<int> { block }, FocusWidth, FocusLift);
            _focusUntil = Time.time + seconds;
        }

        public void ClearFocus()
        {
            _focusUntil = 0f;
            Fill(_focus.sharedMesh, new List<int>(), FocusWidth, FocusLift);
        }

        public bool FocusShown => _focus != null && _focus.sharedMesh.vertexCount > 0;

        void Update()
        {
            if (_focusUntil > 0f && Time.time > _focusUntil)
            {
                _focusUntil = 0f;
                Fill(_focus.sharedMesh, new List<int>(), FocusWidth, FocusLift);
            }
            int block = DistrictUI.PointerOverUI ? -1 : brush.HoverBlock;
            if (block == _shownBlock && brush.Radius == _shownRadius) return;
            _shownBlock = block;
            _shownRadius = brush.Radius;
            Fill(_area.sharedMesh, block >= 0 ? brush.Footprint(block) : new List<int>(), AreaWidth, AreaLift);
            Fill(_hover.sharedMesh, block >= 0 ? new List<int> { block } : new List<int>(), HoverWidth, HoverLift);
        }

        MeshFilter Outline(string name, Color color)
        {
            var go = new GameObject(name, typeof(MeshFilter), typeof(MeshRenderer));
            go.transform.SetParent(transform, false);
            var r = go.GetComponent<MeshRenderer>();
            r.sharedMaterial = material;
            r.shadowCastingMode = ShadowCastingMode.Off;
            r.receiveShadows = false;
            var props = new MaterialPropertyBlock();
            props.SetColor("_BaseColor", color);
            r.SetPropertyBlock(props);
            var filter = go.GetComponent<MeshFilter>();
            filter.sharedMesh = new Mesh { name = name };
            return filter;
        }

        // Four strips per block, along the inside of its edges.
        void Fill(Mesh mesh, List<int> blocks, float width, float lift)
        {
            var d = district.Data;
            var verts = new List<Vector3>();
            var tris = new List<int>();
            foreach (int b in blocks)
            {
                float s = d.blockSize, x0 = (b % d.cols) * s, z0 = (b / d.cols) * s, x1 = x0 + s, z1 = z0 + s;
                Strip(verts, tris, x0, z0, x1, z0 + width, lift);          // south edge
                Strip(verts, tris, x0, z1 - width, x1, z1, lift);          // north edge
                Strip(verts, tris, x0, z0 + width, x0 + width, z1 - width, lift);  // west edge
                Strip(verts, tris, x1 - width, z0 + width, x1, z1 - width, lift);  // east edge
            }
            mesh.Clear();
            mesh.SetVertices(verts);
            mesh.SetTriangles(tris, 0);
            mesh.RecalculateBounds();
        }

        // A flat rectangle facing up (clockwise seen from above, Unity's front face).
        static void Strip(List<Vector3> v, List<int> t, float xa, float za, float xb, float zb, float y)
        {
            int i = v.Count;
            v.Add(new Vector3(xa, y, za));
            v.Add(new Vector3(xa, y, zb));
            v.Add(new Vector3(xb, y, zb));
            v.Add(new Vector3(xb, y, za));
            t.Add(i); t.Add(i + 1); t.Add(i + 2);
            t.Add(i); t.Add(i + 2); t.Add(i + 3);
        }
    }
}
