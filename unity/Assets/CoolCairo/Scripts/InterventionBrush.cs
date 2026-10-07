using UnityEngine;

namespace CoolCairo
{
    // Paint interventions onto blocks: left mouse applies, right mouse (held) erases.
    // Works per block, never per building, matching the 100 m thermal resolution.
    public class InterventionBrush : MonoBehaviour
    {
        [SerializeField] DistrictView district;
        [SerializeField] Camera cam;
        [SerializeField, Tooltip("Share added per second while painting")] float rate = 2f;
        [SerializeField, Range(0, 5), Tooltip("Radius in blocks")] int radius = 1;

        public Intervention Tool { get; set; } = Intervention.CoolRoof;
        public int Radius { get => radius; set => radius = Mathf.Clamp(value, 0, 5); }
        public int HoverBlock { get; private set; } = -1;

        readonly Plane _ground = new Plane(Vector3.up, Vector3.zero);

        void Update()
        {
            HoverBlock = -1;
            var ray = cam.ScreenPointToRay(Input.mousePosition);
            if (!_ground.Raycast(ray, out float dist)) return;
            HoverBlock = district.Data.BlockAt(ray.GetPoint(dist));
            if (HoverBlock < 0 || DistrictUI.PointerOverUI || Input.GetKey(KeyCode.LeftAlt)) return;

            float sign = Input.GetMouseButton(0) ? 1f : Input.GetMouseButton(1) ? -1f : 0f;
            if (sign == 0f) return;
            PaintAround(HoverBlock, sign * rate * Time.deltaTime);
        }

        void PaintAround(int centre, float amount)
        {
            foreach (int block in Footprint(centre)) district.Model.Apply(Tool, block, amount);
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
