using UnityEngine;

namespace CoolCairo
{
    // Paint interventions onto blocks: left mouse applies, right mouse (held) erases.
    // Works per block, never per building, matching the 100 m thermal resolution.
    // Each stroke (button down to button up) is one undo step.
    public class InterventionBrush : MonoBehaviour
    {
        [SerializeField] DistrictView district;
        [SerializeField] Camera cam;
        [SerializeField, Tooltip("Share added per second while painting")] float rate = 2f;
        [SerializeField, Range(0, 5), Tooltip("Radius in blocks")] int radius = 1;

        public Intervention Tool { get; set; } = Intervention.CoolRoof;
        public int Radius { get => radius; set => radius = Mathf.Clamp(value, 0, 5); }
        public int HoverBlock { get; private set; } = -1;
        public bool Painting { get; private set; }    // left or right button held over the map

        // A stroke touched these blocks (centre first); PaintFeedback flashes them.
        public event System.Action<int, System.Collections.Generic.List<int>> Painted;

        readonly Plane _ground = new Plane(Vector3.up, Vector3.zero);
        bool _stroke;
        int _strokeVersion;

        void Update()
        {
            // Stroke ends when both buttons are up; one that changed nothing leaves no undo step.
            if (_stroke && !Input.GetMouseButton(0) && !Input.GetMouseButton(1))
            {
                _stroke = false;
                if (district.Model.Version == _strokeVersion) district.Model.DropUndo();
            }
            HoverBlock = -1;
            Painting = false;
            var ray = cam.ScreenPointToRay(Input.mousePosition);
            if (!_ground.Raycast(ray, out float dist)) return;
            HoverBlock = district.Data.BlockAt(ray.GetPoint(dist));
            if (HoverBlock < 0 || DistrictUI.PointerOverUI || Input.GetKey(KeyCode.LeftAlt)) return;

            float sign = Input.GetMouseButton(0) ? 1f : Input.GetMouseButton(1) ? -1f : 0f;
            if (sign == 0f) return;
            Painting = true;
            if (!_stroke)
            {
                _stroke = true;
                district.Model.SaveUndo();
                _strokeVersion = district.Model.Version;
            }
            PaintAround(HoverBlock, sign * rate * Time.deltaTime);
        }

        void PaintAround(int centre, float amount)
        {
            var blocks = Footprint(centre);
            foreach (int block in blocks) district.Model.Apply(Tool, block, amount);
            Painted?.Invoke(centre, blocks);
        }

        // The blocks one stroke covers: a circle of the brush radius around the centre block.
        // BlockHighlight outlines exactly these, so what you see is what gets painted.
        public System.Collections.Generic.List<int> Footprint(int centre)
        {
            var d = district.Data;
            var blocks = new System.Collections.Generic.List<int>();
            int cr = centre / d.cols, cc = centre % d.cols;
            for (int r = cr - radius; r <= cr + radius; r++)
            for (int c = cc - radius; c <= cc + radius; c++)
            {
                if (r < 0 || r >= d.rows || c < 0 || c >= d.cols) continue;
                if ((r - cr) * (r - cr) + (c - cc) * (c - cc) > radius * radius) continue;
                blocks.Add(r * d.cols + c);
            }
            return blocks;
        }
    }
}
