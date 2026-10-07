using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace CoolCairo
{
    // Automated checks of the real app, run inside the built player:
    //   CoolCairo.exe -selftest -logFile selftest.log
    // It flies into Nasr City by itself, checks the heat colour schemes, the brush footprint and
    // block highlight, and the analysis-maps popup, logs one "[SelfTest] PASS/FAIL" line per check
    // and a summary, then quits with exit code 0 (all passed) or 1 (any failed).
    // Does nothing unless the flag is present.
    public class SelfTest : MonoBehaviour
    {
        int _passed, _failed;
        readonly List<string> _failures = new List<string>();

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Boot()
        {
            if (!Environment.GetCommandLineArgs().Contains("-selftest")) return;
            var go = new GameObject("SelfTest");
            DontDestroyOnLoad(go);
            go.AddComponent<SelfTest>().StartCoroutine(go.GetComponent<SelfTest>().Run());
        }

        IEnumerator Run()
        {
            Debug.Log("[SelfTest] start");
            IntroController intro = null;
            while ((intro = FindFirstObjectByType<IntroController>()) == null || !intro.ReadyForInput) yield return null;
            intro.ChooseCity(0);

            DistrictView district = null;
            while ((district = FindFirstObjectByType<DistrictView>()) == null || district.Model == null) yield return null;
            var ui = FindFirstObjectByType<DistrictUI>();
            var brush = FindFirstObjectByType<InterventionBrush>();
            var highlight = FindFirstObjectByType<BlockHighlight>();
            yield return null;   // let DistrictUI.Start and the first Update run
            yield return null;

            yield return HeatPalettes(district, ui);
            yield return FootprintAndHighlight(district, brush, highlight);
            yield return AnalysisMaps(district, ui);
            Unchanged(district);

            Debug.Log($"[SelfTest] SUMMARY {_passed} passed, {_failed} failed" +
                      (_failed > 0 ? ": " + string.Join("; ", _failures) : ""));
            Application.Quit(_failed > 0 ? 1 : 0);
        }

        // ---------- 1. heat colour schemes ----------

        IEnumerator HeatPalettes(DistrictView d, DistrictUI ui)
        {
            float reference = d.Data.model.heatReferenceC;
            Check("palette: default is Report", d.Palette == HeatPalette.Report, $"was {d.Palette}");

            d.SetPalette(HeatPalette.Report);
            Check("palette Report: typical block is light grey #F0EFEC",
                  Near(d.HeatColor(reference), Hex(0xF0EFEC)), Show(d.HeatColor(reference)));
            var cool = d.HeatColor(reference - 1.5f);
            var hot = d.HeatColor(reference + 1.5f);
            Check("palette Report: cooler than typical is blue", cool.b > cool.r + 0.1f, Show(cool));
            Check("palette Report: hotter than typical is orange", hot.r > hot.b + 0.1f, Show(hot));

            d.SetPalette(HeatPalette.Inferno);
            Check("palette Inferno: coolest end black, hottest pale yellow",
                  Near(d.HeatColor(d.HeatMin), Hex(0x000004)) && Near(d.HeatColor(d.HeatMax), Hex(0xFCFFA4)),
                  Show(d.HeatColor(d.HeatMin)) + " .. " + Show(d.HeatColor(d.HeatMax)));

            d.SetPalette(HeatPalette.Warm);
            Check("palette Warm: coolest end pale yellow, hottest dark red",
                  Near(d.HeatColor(d.HeatMin), Hex(0xFFFFB2)) && Near(d.HeatColor(d.HeatMax), Hex(0xBD0026)),
                  Show(d.HeatColor(d.HeatMin)) + " .. " + Show(d.HeatColor(d.HeatMax)));

            // The buttons in the colour key switch the scheme.
            Button("Palette_Inferno").onClick.Invoke();
            Check("palette buttons: Inferno button selects Inferno", d.Palette == HeatPalette.Inferno, $"was {d.Palette}");
            Button("Palette_Report").onClick.Invoke();
            Check("palette buttons: Report button selects Report", d.Palette == HeatPalette.Report, $"was {d.Palette}");

            // The map really recolours: a block's ground pixel changes with the scheme.
            d.SetMode(ViewMode.Heat);
            var ground = (Texture2D)typeof(DistrictView).GetField("_groundTex", BindingFlags.NonPublic | BindingFlags.Instance).GetValue(d);
            int block = Enumerable.Range(0, d.Data.BlockCount).First(d.Model.IsValid);
            var reportPixel = ground.GetPixel(block % d.Data.cols, block / d.Data.cols);
            d.SetPalette(HeatPalette.Inferno);
            var infernoPixel = ground.GetPixel(block % d.Data.cols, block / d.Data.cols);
            Check("palette: the ground map recolours when the scheme changes", !Near(reportPixel, infernoPixel),
                  Show(reportPixel) + " vs " + Show(infernoPixel));
            d.SetPalette(HeatPalette.Report);

            // The scheme buttons only show in the Surface heat view; the key's title names the reference.
            d.SetMode(ViewMode.Heat);
            yield return null;
            var row = Find("LegendPalettes");
            Check("legend: scheme buttons shown in Surface heat", row != null && row.activeInHierarchy);
            Check("legend: Report title names the typical block",
                  Text("LegendTitle").Contains("typical block"), Text("LegendTitle"));
            d.SetMode(ViewMode.Materials);
            yield return null;
            Check("legend: scheme buttons hidden in Materials", row != null && !row.activeInHierarchy);
        }

        // ---------- 2. brush footprint and block highlight ----------

        IEnumerator FootprintAndHighlight(DistrictView d, InterventionBrush brush, BlockHighlight highlight)
        {
            int cols = d.Data.cols;
            int interior = 12 * cols + 12;   // row 12, column 12: far from the edges
            brush.Radius = 0;
            Check("footprint: radius 0 is one block", Same(brush.Footprint(interior), new[] { interior }));
            brush.Radius = 1;
            Check("footprint: radius 1 is a plus of 5 blocks", Same(brush.Footprint(interior),
                  new[] { interior, interior - 1, interior + 1, interior - cols, interior + cols }));
            Check("footprint: radius 1 in the corner is 3 blocks", brush.Footprint(0).Count == 3,
                  $"{brush.Footprint(0).Count}");
            brush.Radius = 2;
            Check("footprint: radius 2 is 13 blocks", brush.Footprint(interior).Count == 13, $"{brush.Footprint(interior).Count}");

            // Painting changes exactly the outlined blocks, nothing else.
            brush.Radius = 1;
            brush.Tool = Intervention.CoolRoof;
            d.Model.ResetAll();
            typeof(InterventionBrush).GetMethod("PaintAround", BindingFlags.NonPublic | BindingFlags.Instance)
                .Invoke(brush, new object[] { interior, 1f });
            var painted = Enumerable.Range(0, d.Data.BlockCount).Where(b => d.Model.Share(Intervention.CoolRoof, b) > 0f);
            var expected = brush.Footprint(interior).Where(d.Model.IsValid);
            Check("footprint: painting changes exactly the footprint blocks", Same(painted.ToList(), expected.ToArray()),
                  $"painted {painted.Count()}, expected {expected.Count()}");
            d.Model.ResetAll();

            // The highlight's two outlines exist, and its mesh draws 4 strips (16 corners) per block.
            Check("highlight: hover and brush-area outlines exist",
                  highlight != null && Find("HoverOutline") != null && Find("BrushArea") != null);
            var mesh = new Mesh();
            typeof(BlockHighlight).GetMethod("Fill", BindingFlags.NonPublic | BindingFlags.Instance)
                .Invoke(highlight, new object[] { mesh, brush.Footprint(interior), 3f, 0.6f });
            float s = d.Data.blockSize;
            var area = new Bounds();
            area.SetMinMax(new Vector3((12 - 1) * s, 0.5f, (12 - 1) * s), new Vector3((12 + 2) * s, 0.7f, (12 + 2) * s));
            Check("highlight: outline mesh is 4 strips per footprint block, on those blocks",
                  mesh.vertexCount == 16 * 5 && area.Contains(mesh.bounds.min) && area.Contains(mesh.bounds.max),
                  $"{mesh.vertexCount} vertices, bounds {mesh.bounds}");
            yield return null;
        }

        // ---------- 3. analysis maps popup ----------

        IEnumerator AnalysisMaps(DistrictView d, DistrictUI ui)
        {
            var figures = (AnalysisFigure[])typeof(DistrictUI).GetField("figures", BindingFlags.NonPublic | BindingFlags.Instance).GetValue(ui);
            Check("figures: 7 linked, all with an image", figures != null && figures.Length == 7 && figures.All(f => f.image != null),
                  $"{figures?.Length} linked, {figures?.Count(f => f.image == null)} without image");
            int Count(ViewMode m) => figures.Count(f => f.view == m);
            Check("figures: Materials 1, Surface heat 3, Heat risk 2, Growth 1",
                  Count(ViewMode.Materials) == 1 && Count(ViewMode.Heat) == 3 && Count(ViewMode.Risk) == 2 && Count(ViewMode.Growth) == 1);
            Check("figures: images are sharp but not oversized (500-2048 px wide)",
                  figures.All(f => f.image.width >= 500 && f.image.width <= 2048),
                  string.Join(", ", figures.Select(f => f.image.width)));
            Check("figures: the EnMAP chart carries the DLR credit",
                  figures.Any(f => f.image.name.Contains("hyperspectral") && f.caption.Contains("© DLR")));

            d.SetMode(ViewMode.Heat);
            yield return null;
            var open = Button("FiguresButton");
            Check("figures button: shows the count for Surface heat",
                  open.GetComponentInChildren<TextMeshProUGUI>().text.Contains("(3)"), open.GetComponentInChildren<TextMeshProUGUI>().text);

            open.onClick.Invoke();
            yield return null;
            var popup = Find("FigurePopup");
            var image = Find("FigureImage").GetComponent<RawImage>();
            var first = figures.First(f => f.view == ViewMode.Heat);
            Check("popup: opens on the first Surface heat map", popup.activeSelf && image.texture == first.image &&
                  Text("FigureCount") == "1 / 3", $"active {popup.activeSelf}, count {Text("FigureCount")}");
            Check("popup: keeps the figure's shape",
                  Mathf.Abs(image.GetComponent<AspectRatioFitter>().aspectRatio - first.image.width / (float)first.image.height) < 0.01f);
            Check("popup: Previous disabled on the first map", !Button("FigurePrev").interactable && Button("FigureNext").interactable);

            Button("FigureNext").onClick.Invoke();
            Button("FigureNext").onClick.Invoke();
            Check("popup: Next pages to the last map and stops", Text("FigureCount") == "3 / 3" && !Button("FigureNext").interactable,
                  Text("FigureCount"));

            Button("FigureClose").onClick.Invoke();
            yield return null;
            Check("popup: × closes it", !popup.activeSelf);

            d.SetMode(ViewMode.Growth);
            yield return null;
            Check("figures button: singular label for Growth (1 map)",
                  open.GetComponentInChildren<TextMeshProUGUI>().text.StartsWith("Analysis map for"), open.GetComponentInChildren<TextMeshProUGUI>().text);
        }

        // ---------- 4. nothing else changed ----------

        void Unchanged(DistrictView d)
        {
            d.Model.ResetAll();
            float exposure = d.Model.TotalExposure(false);
            Check("unchanged: today's heat exposure is still 6,460 person·°C", Mathf.Abs(exposure - 6460f) < 1f, $"{exposure:N0}");
        }

        // ---------- helpers ----------

        void Check(string name, bool ok, string detail = "")
        {
            if (ok) { _passed++; Debug.Log($"[SelfTest] PASS {name}"); }
            else { _failed++; _failures.Add(name); Debug.LogWarning($"[SelfTest] FAIL {name}: {detail}"); }
        }

        static GameObject Find(string name) =>
            Resources.FindObjectsOfTypeAll<Transform>().FirstOrDefault(t => t.name == name && t.gameObject.scene.IsValid())?.gameObject;

        static Button Button(string name) => Find(name).GetComponent<Button>();
        static string Text(string name) => Find(name).GetComponent<TextMeshProUGUI>().text;

        static bool Same(List<int> a, int[] b) => a.Count == b.Length && !a.Except(b).Any();
        static bool Near(Color a, Color b) => Mathf.Abs(a.r - b.r) < 0.02f && Mathf.Abs(a.g - b.g) < 0.02f && Mathf.Abs(a.b - b.b) < 0.02f;
        static Color Hex(int rgb) => new Color(((rgb >> 16) & 255) / 255f, ((rgb >> 8) & 255) / 255f, (rgb & 255) / 255f);
        static string Show(Color c) => "#" + ColorUtility.ToHtmlStringRGB(c);
    }
}
