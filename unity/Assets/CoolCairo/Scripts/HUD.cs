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

        Rect _panel = new Rect(12, 12, 360, 400);

        void OnGUI()
        {
            var mouse = Event.current.mousePosition;
            PointerOverPanel = _panel.Contains(mouse);
            GUILayout.BeginArea(_panel, GUI.skin.box);

            var d = district.Data;
            var m = district.Model;
            GUILayout.BeginHorizontal();
            GUILayout.Label($"<b>CoolCairo — {d.name}</b>", Rich());
            if (GUILayout.Button("◀ Globe", GUILayout.Width(70)))
                UnityEngine.SceneManagement.SceneManager.LoadScene(0); // Intro is build index 0.
            GUILayout.EndHorizontal();

            GUILayout.Label("View");
            int mode = GUILayout.Toolbar((int)district.Mode, new[] { "Materials", "Surface heat", "Heat risk" });
            if (mode != (int)district.Mode) district.SetMode((ViewMode)mode);

            GUILayout.Label("Intervention (left paint, right erase)");
            brush.Tool = (Intervention)GUILayout.Toolbar((int)brush.Tool, new[] { "Cool roofs", "Street trees" });
            GUILayout.Label($"Brush radius: {brush.Radius} blocks");
            brush.Radius = Mathf.RoundToInt(GUILayout.HorizontalSlider(brush.Radius, 0, 5));
            if (GUILayout.Button("Reset interventions")) m.ResetAll();

            GUILayout.Space(6);
            GUILayout.Label($"District mean surface ΔT: <b>{m.MeanDelta():+0.00;-0.00;0.00} °C</b>", Rich());
            float baseRisk = m.TotalExposure(false), nowRisk = m.TotalExposure();
            float riskPct = baseRisk > 0f ? 100f * (nowRisk - baseRisk) / baseRisk : 0f;
            GUILayout.Label($"Heat exposure: <b>{nowRisk:N0}</b> person·°C ({riskPct:+0;-0;0}%) · " +
                            $"{m.ResidentsInCooledBlocks():N0} of {m.TotalResidents():N0} residents in cooled blocks", Rich());

            int h = brush.HoverBlock;
            if (h >= 0 && m.IsValid(h))
            {
                var b = d.blocks;
                GUILayout.Label(
                    $"Block {h}: surface temp {m.BaselineLst(h):0.0} °C → {m.Lst(h):0.0} °C · " +
                    $"{m.Residents(h):N0} residents · exposure {m.Exposure(h, false):N0} → {m.Exposure(h):N0}\n" +
                    $"{b.darkRoofFrac[h]:P0} dark roof · {b.paleRoofFrac[h]:P0} pale roof · {b.darkGroundFrac[h]:P0} dark ground · {b.vegFrac[h]:P0} vegetation · {b.soilFrac[h]:P0} bare soil");
            }

            GUILayout.FlexibleSpace();
            GUILayout.Label(
                $"<size=10>Land surface temperature, block-level ({d.blockSize:0} m). " +
                $"Model spatial-CV R² {d.model.r2SpatialCv:0.00}, MAE {d.model.maeSpatialCv:0.0} °C, n={d.model.nBlocks}. " +
                $"Cool roofs per coated area: dark {d.model.coolRoofDarkDeltaC:0.0} °C, " +
                $"pale {d.model.coolRoofPaleDeltaC:0.0} °C ({d.model.coolRoofMethod}).</size>",
                Rich());
            GUILayout.EndArea();

            DrawLegend();
        }

        void DrawLegend()
        {
            if (district.Mode == ViewMode.Materials) return;
            bool risk = district.Mode == ViewMode.Risk;
            const int w = 220, hgt = 14, steps = 44;
            var r = new Rect(Screen.width - w - 16, Screen.height - 46, w, hgt);
            if (risk)
                GUI.Label(new Rect(r.x, r.y - 20, w, 20),
                          $"Heat exposure (residents × °C above {district.Data.model.heatReferenceC:0.0} °C)");
            for (int i = 0; i < steps; i++)
            {
                float t = i / (steps - 1f);
                var c = risk ? district.RiskColor(t * district.RiskMax)
                             : district.HeatColor(Mathf.Lerp(district.HeatMin, district.HeatMax, t));
                var cell = new Rect(r.x + t * (w - w / steps), r.y, w / (float)steps + 1, hgt);
                var prev = GUI.color;
                GUI.color = c;
                GUI.DrawTexture(cell, Texture2D.whiteTexture);
                GUI.color = prev;
            }
            if (risk)
            {
                GUI.Label(new Rect(r.x, r.y + hgt, w, 20), "0");
                GUI.Label(new Rect(r.xMax - 60, r.y + hgt, 60, 20), $"{district.RiskMax:N0}+");
                return;
            }
            GUI.Label(new Rect(r.x, r.y + hgt, w, 20), $"{district.HeatMin:0} °C");
            GUI.Label(new Rect(r.xMax - 40, r.y + hgt, 40, 20), $"{district.HeatMax:0} °C");
        }

        static GUIStyle Rich() => new GUIStyle(GUI.skin.label) { richText = true, wordWrap = true };
    }
}
