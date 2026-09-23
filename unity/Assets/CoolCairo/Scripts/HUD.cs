using UnityEngine;

namespace CoolCairo
{
    // Functional placeholder UI (IMGUI). To be replaced by the designed UI; the data it shows
    // (tool, readouts, legend) is the contract the final UI must keep.
    public class HUD : MonoBehaviour
    {
        [SerializeField] DistrictView district;
        [SerializeField] InterventionBrush brush;

        public static bool PointerOverPanel { get; private set; }

        Rect _panel = new Rect(12, 12, 320, 330);

        void OnGUI()
        {
            var mouse = Event.current.mousePosition;
            PointerOverPanel = _panel.Contains(mouse);
            GUILayout.BeginArea(_panel, GUI.skin.box);

            var d = district.Data;
            var m = district.Model;
            GUILayout.Label($"<b>CoolCairo — {d.name}</b>", Rich());

            GUILayout.Label("View");
            int mode = GUILayout.Toolbar((int)district.Mode, new[] { "Materials", "Surface heat" });
            if (mode != (int)district.Mode) district.SetMode((ViewMode)mode);

            GUILayout.Label("Intervention (left paint, right erase)");
            brush.Tool = (Intervention)GUILayout.Toolbar((int)brush.Tool, new[] { "Cool roofs", "Street trees" });
            GUILayout.Label($"Brush radius: {brush.Radius} blocks");
            brush.Radius = Mathf.RoundToInt(GUILayout.HorizontalSlider(brush.Radius, 0, 5));
            if (GUILayout.Button("Reset interventions")) m.ResetAll();

            GUILayout.Space(6);
            GUILayout.Label($"District mean surface ΔT: <b>{m.MeanDelta():+0.00;-0.00;0.00} °C</b>", Rich());

            int h = brush.HoverBlock;
            if (h >= 0 && m.IsValid(h))
            {
                var b = d.blocks;
                GUILayout.Label(
                    $"Block {h}: surface temp {m.BaselineLst(h):0.0} °C → {m.Lst(h):0.0} °C\n" +
                    $"{b.darkRoofFrac[h]:P0} dark roof · {b.darkGroundFrac[h]:P0} dark ground · {b.vegFrac[h]:P0} vegetation");
            }

            GUILayout.FlexibleSpace();
            GUILayout.Label(
                $"<size=10>Land surface temperature, block-level ({d.blockSize:0} m). " +
                $"Model spatial-CV R² {d.model.r2SpatialCv:0.00}, MAE {d.model.maeSpatialCv:0.0} °C, n={d.model.nBlocks}.</size>",
                Rich());
            GUILayout.EndArea();

            DrawLegend();
        }

        void DrawLegend()
        {
            if (district.Mode != ViewMode.Heat) return;
            const int w = 220, hgt = 14, steps = 44;
            var r = new Rect(Screen.width - w - 16, Screen.height - 46, w, hgt);
            for (int i = 0; i < steps; i++)
            {
                float t = i / (steps - 1f);
                var c = district.HeatColor(Mathf.Lerp(district.HeatMin, district.HeatMax, t));
                var cell = new Rect(r.x + t * (w - w / steps), r.y, w / (float)steps + 1, hgt);
                var prev = GUI.color;
                GUI.color = c;
                GUI.DrawTexture(cell, Texture2D.whiteTexture);
                GUI.color = prev;
            }
            GUI.Label(new Rect(r.x, r.y + hgt, w, 20), $"{district.HeatMin:0} °C");
            GUI.Label(new Rect(r.xMax - 40, r.y + hgt, 40, 20), $"{district.HeatMax:0} °C");
        }

        static GUIStyle Rich() => new GUIStyle(GUI.skin.label) { richText = true, wordWrap = true };
    }
}
