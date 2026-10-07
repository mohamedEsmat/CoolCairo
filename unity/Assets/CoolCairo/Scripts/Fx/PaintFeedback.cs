using System.Collections.Generic;
using TMPro;
using UnityEngine;
using UnityEngine.Rendering;

namespace CoolCairo
{
    // What a planner sees while painting: the blocks under the brush pulse green and fade out
    // after the stroke, and the centre block's cooling rises off the map as "−0.6 °C".
    public class PaintFeedback : MonoBehaviour
    {
        [SerializeField] DistrictView district;
        [SerializeField] InterventionBrush brush;
        [SerializeField] Camera cam;
        [SerializeField] Material material;          // CoolCairo/Glow
        [SerializeField] RectTransform labelTemplate; // HUD "FloatLabel", inactive

        const float FlashSeconds = 0.9f;
        const float LabelEvery = 0.35f, LabelSeconds = 1.3f, LabelRise = 80f;
        const float Lift = 1.0f;                      // metres above the ground plane

        readonly Dictionary<int, float> _painted = new Dictionary<int, float>();   // block -> last time
        readonly List<Label> _labels = new List<Label>();
        readonly List<Vector3> _verts = new List<Vector3>();
        readonly List<Color> _colors = new List<Color>();
        readonly List<int> _tris = new List<int>();
        Mesh _mesh;
        float _nextLabel;
        int _lastLabelBlock = -1;
        float _lastLabelValue = float.NaN;

        class Label { public RectTransform rt; public TextMeshProUGUI text; public Vector3 world; public float born; }

        // Labels shown so far (the self-test checks one appears after painting).
        public int LabelsSpawned { get; private set; }

        void Start()
        {
            var go = new GameObject("PaintFlash", typeof(MeshFilter), typeof(MeshRenderer));
            go.transform.SetParent(transform, false);
            var r = go.GetComponent<MeshRenderer>();
            r.sharedMaterial = material;
            r.shadowCastingMode = ShadowCastingMode.Off;
            r.receiveShadows = false;
            _mesh = new Mesh { name = "PaintFlash" };
            _mesh.MarkDynamic();
            go.GetComponent<MeshFilter>().sharedMesh = _mesh;
            brush.Painted += OnPainted;
        }

        void OnDestroy()
        {
            if (brush != null) brush.Painted -= OnPainted;
        }

        void OnPainted(int centre, List<int> blocks)
        {
            float now = Time.time;
            foreach (int b in blocks)
                if (district.Model.IsValid(b)) _painted[b] = now;

            // A label for the centre block every so often, only when its value has moved.
            if (now < _nextLabel || !district.Model.IsValid(centre)) return;
            float delta = district.Model.Lst(centre) - district.Model.BaselineLst(centre);
            if (centre == _lastLabelBlock && Mathf.Abs(delta - _lastLabelValue) < 0.05f) return;
            if (Mathf.Abs(delta) < 0.05f && centre != _lastLabelBlock) return;
            _nextLabel = now + LabelEvery;
            _lastLabelBlock = centre;
            _lastLabelValue = delta;
            Spawn(centre, delta);
        }

        void Spawn(int block, float delta)
        {
            if (labelTemplate == null) return;
            var label = _labels.Find(l => !l.rt.gameObject.activeSelf);
            if (label == null)
            {
                var rt = Instantiate(labelTemplate, labelTemplate.parent);
                label = new Label { rt = rt, text = rt.GetComponent<TextMeshProUGUI>() };
                _labels.Add(label);
            }
            float roof = Mathf.Max(0f, district.Data.blocks.meanHeightM[block]);
            label.world = district.transform.TransformPoint(district.Data.BlockCentre(block) + Vector3.up * (roof + 10f));
            label.born = Time.time;
            bool cooler = delta < -0.005f;
            label.text.text = (cooler ? "−" : "+") + Mathf.Abs(delta).ToString("0.0") + " °C";
            label.text.color = cooler ? HudStyle.Good : HudStyle.Accent;
            label.rt.gameObject.SetActive(true);
            label.rt.SetAsLastSibling();
            LabelsSpawned++;
        }

        void Update()
        {
            UpdateFlash();
            UpdateLabels();
        }

        void UpdateFlash()
        {
            _verts.Clear();
            _colors.Clear();
            _tris.Clear();
            float now = Time.time, s = district.Data.blockSize, inset = s * 0.06f;
            // While the button is held the stroke throbs; afterwards it fades out.
            float throb = brush.Painting ? 0.75f + 0.25f * Mathf.Sin(now * 12f) : 1f;
            List<int> done = null;
            foreach (var kv in _painted)
            {
                float age = (now - kv.Value) / FlashSeconds;
                if (age >= 1f) { (done ??= new List<int>()).Add(kv.Key); continue; }
                var c = HudStyle.Good;
                c.a = 0.55f * (1f - age) * (1f - age) * throb;
                var centre = district.Data.BlockCentre(kv.Key);
                float h = s / 2f - inset;
                int v = _verts.Count;
                _verts.Add(centre + new Vector3(-h, Lift, -h));
                _verts.Add(centre + new Vector3(-h, Lift, h));
                _verts.Add(centre + new Vector3(h, Lift, h));
                _verts.Add(centre + new Vector3(h, Lift, -h));
                for (int k = 0; k < 4; k++) _colors.Add(c);
                _tris.AddRange(new[] { v, v + 1, v + 2, v, v + 2, v + 3 });
            }
            if (done != null) foreach (int b in done) _painted.Remove(b);
            _mesh.Clear();
            _mesh.SetVertices(_verts);
            _mesh.SetColors(_colors);
            _mesh.SetUVs(0, new Vector2[_verts.Count]);   // uv 0: flat quad, no plume
            _mesh.SetUVs(1, new Vector2[_verts.Count]);
            _mesh.SetTriangles(_tris, 0);
        }

        void UpdateLabels()
        {
            if (_labels.Count == 0) return;
            var canvas = (RectTransform)labelTemplate.parent;
            foreach (var l in _labels)
            {
                if (!l.rt.gameObject.activeSelf) continue;
                float age = (Time.time - l.born) / LabelSeconds;
                var screen = cam.WorldToScreenPoint(l.world);
                if (age >= 1f || screen.z < 0f) { l.rt.gameObject.SetActive(false); continue; }
                RectTransformUtility.ScreenPointToLocalPointInRectangle(canvas, screen, null, out var local);
                float ease = 1f - (1f - age) * (1f - age);
                l.rt.anchoredPosition = local + canvas.rect.size / 2f + new Vector2(0f, LabelRise * ease);
                // Pop in, then drift up and fade.
                float pop = age < 0.12f ? Mathf.Lerp(0.6f, 1.15f, age / 0.12f) : Mathf.Lerp(1.15f, 1f, Mathf.Min(1f, (age - 0.12f) / 0.15f));
                l.rt.localScale = Vector3.one * pop;
                var c = l.text.color;
                c.a = age < 0.55f ? 1f : 1f - (age - 0.55f) / 0.45f;
                l.text.color = c;
            }
        }
    }
}
