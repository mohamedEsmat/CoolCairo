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
    // block highlight, the analysis-maps popup and the live HUD effects (fades, animated readouts,
    // paint feedback, heat shimmer, ticker, sun, idle drift), logs one "[SelfTest] PASS/FAIL" line per check
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
            CityFiles();
            intro.ChooseCity(0);

            DistrictView district = null;
            while ((district = FindFirstObjectByType<DistrictView>()) == null || district.Model == null) yield return null;
            Check("cities: choosing Cairo opens Nasr City", CityCatalog.CairoSelected && district.Data.name == "Nasr City",
                  district.Data.name);
            var ui = FindFirstObjectByType<DistrictUI>();
            var brush = FindFirstObjectByType<InterventionBrush>();
            var highlight = FindFirstObjectByType<BlockHighlight>();
            yield return null;   // let DistrictUI.Start and the first Update run
            yield return null;

            yield return HeatPalettes(district, ui);
            yield return FootprintAndHighlight(district, brush, highlight);
            yield return AnalysisMaps(district, ui);
            yield return PlanPanel(district);
            yield return LiveHud(district, ui, brush);
            Unchanged(district);
            yield return SecondCity();

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
            // (Switching cross-fades for 0.4 s, so read the pixels once each fade has finished.)
            d.SetMode(ViewMode.Heat);
            yield return Settle(d);
            var ground = Ground(d);
            int block = Enumerable.Range(0, d.Data.BlockCount).First(d.Model.IsValid);
            var reportPixel = ground.GetPixel(block % d.Data.cols, block / d.Data.cols);
            d.SetPalette(HeatPalette.Inferno);
            yield return Settle(d);
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
            open.onClick.Invoke();
            yield return null;
            Check("popup: a single map has no Previous / Next", !Button("FigurePrev").gameObject.activeSelf &&
                  !Button("FigureNext").gameObject.activeSelf && Text("FigureKeys") == "ESC TO CLOSE", Text("FigureKeys"));
            Button("FigureClose").onClick.Invoke();
            yield return null;
        }

        // ---------- 4. plan results panel ----------

        IEnumerator PlanPanel(DistrictView d)
        {
            var panel = FindFirstObjectByType<PlanDashboard>();
            var model = d.Model;
            while (model.Undo()) { }   // earlier tests left steps behind
            model.ResetAll();          // start from no plan at all
            Check("plan panel: closed at start, the button opens it", panel != null && !panel.Open &&
                  InvokeAndReturn(() => Button(PlanDashboard.ToggleName).onClick.Invoke(), () => panel.Open));
            Check("plan panel: the colour key under it hides while it is open", !Find(HudStyle.Legend).activeSelf);
            yield return null;

            // Plan builder: its defaults are the report's plan; any other plan previews exactly
            // what applying it does.
            Button(PlanDashboard.TabBuild).onClick.Invoke();
            yield return null;
            Check("plan builder: the default plan previews the report's −74% (1,686 person·°C, 192 blocks)",
                  Mathf.Abs(panel.LastPreview.exposure - 1686f) < 1f && panel.LastPreview.blocks == 192 &&
                  Text(PlanDashboard.BuildPreview) == "−74%",
                  $"{panel.LastPreview.exposure:N1}, {panel.LastPreview.blocks} blocks, {Text(PlanDashboard.BuildPreview)}");
            Button(PlanDashboard.BuildMeasurePrefix + Intervention.CoolRoof).onClick.Invoke();
            Button(PlanDashboard.BuildMeasurePrefix + Intervention.PocketPark).onClick.Invoke();
            Button(PlanDashboard.BuildMeasurePrefix + Intervention.Trees).onClick.Invoke();
            Find(PlanDashboard.BuildShare).GetComponent<Slider>().value = 100;
            yield return null;
            float treesEverywhere = model.ExposureIfEverywhere(Intervention.Trees);
            Check("plan builder: street trees in every block preview the report's one-measure figure (−24%)",
                  Mathf.Abs(panel.LastPreview.exposure - treesEverywhere) < 0.5f,
                  $"{panel.LastPreview.exposure:N1} vs {treesEverywhere:N1}");
            Button(PlanDashboard.BuildApply).onClick.Invoke();
            yield return null;
            Check("plan builder: applying gives exactly the preview, and one Undo takes it back",
                  Mathf.Abs(model.TotalExposure() - panel.LastPreview.exposure) < 0.5f && model.Undo() && !model.HasPlan,
                  $"{model.TotalExposure():N1} vs {panel.LastPreview.exposure:N1}");
            Button(PlanDashboard.BuildDefaults).onClick.Invoke();
            var roofsParks = new[] { true, false, false, true };
            var byRisk = model.Preview(roofsParks, RankBy.HeatRisk, 1f / 3f, 1f);
            var byPotential = model.Preview(roofsParks, RankBy.CoolingPotential, 1f / 3f, 1f);
            Check("plan builder: ranking by cooling potential removes at least as much as by heat risk (same blocks count)",
                  byPotential.blocks == byRisk.blocks && byPotential.exposure <= byRisk.exposure + 0.01f,
                  $"potential {byPotential.exposure:N1} vs risk {byRisk.exposure:N1} person·°C");
            Button(PlanDashboard.TabResults).onClick.Invoke();
            yield return null;

            // One measure in every block, as the report: −41 / −24 / −52 / −60 %.
            float before = model.TotalExposure(false);
            var pct = new[] { Intervention.CoolRoof, Intervention.Trees, Intervention.CoolPavement, Intervention.PocketPark }
                .Select(k => 100f * (before - model.ExposureIfEverywhere(k)) / before).ToArray();
            Check("plan panel: one measure everywhere matches the report (−41/−24/−52/−60%)",
                  Mathf.RoundToInt(pct[0]) == 41 && Mathf.RoundToInt(pct[1]) == 24 &&
                  Mathf.RoundToInt(pct[2]) == 52 && Mathf.RoundToInt(pct[3]) == 60,
                  string.Join(" / ", pct.Select(p => p.ToString("0.0"))));

            // The targeted plan: the report's −74% (6,460 → 1,686 person·°C, 22,588 residents).
            Button(PlanDashboard.TargetedName).onClick.Invoke();
            yield return null;
            float after = model.TotalExposure();
            Check("plan panel: the targeted plan removes 74% (6,460 → 1,686 person·°C)",
                  Mathf.Abs(after - 1686f) < 1f && Text(PlanDashboard.HeadlineName) == "−74%",
                  $"{after:N1}, headline {Text(PlanDashboard.HeadlineName)}");
            int valid = Enumerable.Range(0, d.Data.BlockCount).Count(model.IsValid);
            Check("plan panel: it treats the riskiest third of blocks, 22,588 residents cooled",
                  model.TreatedBlocks() == valid / 3 && Mathf.Abs(model.ResidentsInCooledBlocks() - 22588f) < 1f,
                  $"{model.TreatedBlocks()} of {valid} blocks, {model.ResidentsInCooledBlocks():N0} residents");
            float aboveBefore = model.ResidentsAboveTypical(false), aboveAfter = model.ResidentsAboveTypical();
            var cooled = model.TreatedCooling();
            Check("plan panel: residents in above-typical heat 10,517 → 2,503; treated blocks cool 1.33 °C, up to 3.2",
                  Mathf.Abs(aboveBefore - 10517f) < 1f && Mathf.Abs(aboveAfter - 2503f) < 1f &&
                  cooled.blocks == 192 && Mathf.Abs(cooled.after - cooled.before + 1.33f) < 0.01f &&
                  Mathf.Abs(cooled.maxCooling + 3.23f) < 0.01f,
                  $"{aboveBefore:N0} → {aboveAfter:N0}; {cooled.blocks} blocks {cooled.before:0.00} → {cooled.after:0.00}, max {cooled.maxCooling:0.00}");
            yield return null;
            Check("readouts: with a plan the temperature card shows the treated blocks",
                  Find(HudStyle.KpiDelta).transform.Find(HudStyle.KpiSub).GetComponent<TextMeshProUGUI>().text.StartsWith("192 blocks · up to −3.2") &&
                  Find(HudStyle.KpiDelta).GetComponentsInChildren<TextMeshProUGUI>().Any(t => t.text.Contains("TREATED")),
                  Find(HudStyle.KpiDelta).transform.Find(HudStyle.KpiSub).GetComponent<TextMeshProUGUI>().text);
            var removed = model.ExposureRemovedByMeasure();
            Check("plan panel: the measures' shares add up to the total removed (roofs + parks only)",
                  Mathf.Abs(removed.Sum() - (before - after)) < 0.5f && removed[(int)Intervention.Trees] == 0f &&
                  removed[(int)Intervention.CoolPavement] == 0f && removed[(int)Intervention.CoolRoof] > 0f &&
                  removed[(int)Intervention.PocketPark] > 0f,
                  $"sum {removed.Sum():N1} vs {before - after:N1}");

            // Riskiest blocks: ten, most exposure first; a click flies there and outlines the block.
            Button(PlanDashboard.TabRiskiest).onClick.Invoke();
            yield return null;
            var shown = panel.RiskBlocksShown.ToList();
            int top = Enumerable.Range(0, d.Data.BlockCount).OrderByDescending(b => model.Exposure(b)).First();
            bool sorted = shown.Zip(shown.Skip(1), (a, b) => model.Exposure(a) >= model.Exposure(b)).All(x => x);
            Check("plan panel: the riskiest list shows 10 blocks, most exposure first",
                  shown.Count == 10 && sorted && shown[0] == top, $"{shown.Count} rows, first {shown.FirstOrDefault()} vs {top}");
            Button(PlanDashboard.RiskRowPrefix + 0).onClick.Invoke();
            yield return new WaitForSeconds(1.2f);
            var cam = FindFirstObjectByType<OrbitCamera>();
            float s = d.Data.blockSize;
            var centre = new Vector3((top % d.Data.cols + 0.5f) * s, 0f, (top / d.Data.cols + 0.5f) * s);
            Check("plan panel: a click flies the camera to the block and outlines it",
                  Vector3.Distance(cam.Target, centre) < 1f && FindFirstObjectByType<BlockHighlight>().FocusShown,
                  $"target {cam.Target}, block centre {centre}");
            yield return new WaitForSeconds(4.5f);   // longer than a plain focus outline lasts
            var dui = FindFirstObjectByType<DistrictUI>();
            var card = Find(HudStyle.Tooltip);
            Check("plan panel: the chosen block stays outlined and its info card opens (pinned)",
                  dui.PinnedBlock == top && FindFirstObjectByType<BlockHighlight>().FocusShown && card.activeSelf &&
                  Text(HudStyle.TooltipTitle).Contains($"BLOCK {top:0000}") && Text(HudStyle.TooltipTitle).Contains("PINNED"),
                  $"pinned {dui.PinnedBlock}, card {card.activeSelf}, title {Text(HudStyle.TooltipTitle)}");
            dui.Unpin();

            Check("plan panel: one Undo takes the targeted plan back", model.Undo() && !model.HasPlan);
            Button(PlanDashboard.TabResults).onClick.Invoke();
            Button(PlanDashboard.ToggleName).onClick.Invoke();
            yield return null;
            Check("plan panel: the button closes it again, the colour key comes back", !panel.Open && Find(HudStyle.Legend).activeSelf);
        }

        static bool InvokeAndReturn(System.Action action, System.Func<bool> result)
        {
            action();
            return result();
        }

        // ---------- 5. live HUD ----------

        IEnumerator LiveHud(DistrictView d, DistrictUI ui, InterventionBrush brush)
        {
            // Smooth view changes: the map is mid-way between the two views, then lands on the new one.
            d.SetMode(ViewMode.Heat);
            yield return Settle(d);
            int block = Enumerable.Range(0, d.Data.BlockCount).First(d.Model.IsValid);
            Color Pixel() => Ground(d).GetPixel(block % d.Data.cols, block / d.Data.cols);
            var heat = Pixel();
            d.SetMode(ViewMode.Materials);
            Check("fade: switching view starts a cross-fade", d.Fading);
            float started = Time.time;
            yield return new WaitForSeconds(FadeHalf);   // half-way; the fade eases in and out
            var middle = Pixel();
            yield return Settle(d);
            float took = Time.time - started;
            var materials = Pixel();
            Check("fade: mid-fade colour lies between the two views, then lands on the new one",
                  !Near(middle, heat) && !Near(middle, materials) && Near(materials, MaterialsColor(d, block)),
                  $"{Show(heat)} → {Show(middle)} → {Show(materials)}");
            Check("fade: finishes in about 0.4 s", took > 0.3f && took < 0.8f, $"{took:0.00} s");

            // Painting: the result cards glow and count, a "−x °C" label rises, the blocks flash.
            d.SetMode(ViewMode.Heat);
            yield return Settle(d);
            d.Model.ResetAll();
            yield return new WaitForSeconds(1.5f);   // let the readouts finish their arrival count-up
            Check("readouts: before a plan the exposure card says so", ExposureSub().Contains("no plan yet"),
                  ExposureSub());
            var feedback = FindFirstObjectByType<PaintFeedback>();
            int labelsBefore = feedback.LabelsSpawned;
            int hot = HottestBlock(d);
            brush.Radius = 1;
            brush.Tool = Intervention.CoolRoof;
            typeof(InterventionBrush).GetMethod("PaintAround", BindingFlags.NonPublic | BindingFlags.Instance)
                .Invoke(brush, new object[] { hot, 1f });
            yield return null;
            var glow = Find(HudStyle.KpiExposure).transform.Find(HudStyle.KpiFlash).GetComponent<Image>();
            Check("readouts: the exposure card glows green after cooling", glow.color.a > 0.05f && glow.color.g > glow.color.r,
                  Show(glow.color) + $" a={glow.color.a:0.00}");
            float target = d.Model.TotalExposure();
            Check("readouts: the number counts towards the new value instead of jumping",
                  Mathf.Abs(ui.ShownKpis.exposure - target) > 0.5f, $"shown {ui.ShownKpis.exposure:N1}, target {target:N1}");
            Check("paint: a floating temperature label appears", feedback.LabelsSpawned > labelsBefore,
                  $"{feedback.LabelsSpawned - labelsBefore} new");
            var label = Resources.FindObjectsOfTypeAll<TextMeshProUGUI>()
                .FirstOrDefault(t => t.name.StartsWith(HudStyle.FloatLabel) && t.gameObject.activeInHierarchy);
            float expected = d.Model.Lst(hot) - d.Model.BaselineLst(hot);
            Check("paint: the label shows the block's cooling", label != null && label.text == "−" + (-expected).ToString("0.0") + " °C",
                  $"{label?.text} vs {expected:0.00}");
            var flash = Find("PaintFlash").GetComponent<MeshFilter>().sharedMesh;
            Check("paint: the painted blocks flash (one quad per footprint block)",
                  flash.vertexCount == 4 * brush.Footprint(hot).Count(d.Model.IsValid), $"{flash.vertexCount} vertices");
            var rings = FindFirstObjectByType<TreatmentOverlay>();
            int treated = brush.Footprint(hot).Count(d.Model.IsValid);
            Check("rings: every painted block keeps a cool-roof ring", rings != null && rings.RingCount == treated,
                  $"{rings?.RingCount} rings, {treated} painted blocks");
            var keys = Find(HudStyle.TreatmentKeys);
            Check("rings: the legend shows the ring key once something is painted", keys != null && keys.activeInHierarchy);
            var coolRoof = d.MaterialLegend().First(e => e.label.StartsWith("Cool roof")).color;
            var pale = d.MaterialLegend().First(e => e.label.StartsWith("Pale")).color;
            Check("materials: coated roofs stand out from pale roofs (distinct cyan)",
                  coolRoof.b - coolRoof.r > 0.25f && Mathf.Abs(coolRoof.b - pale.b) > 0.2f, Show(coolRoof) + " vs " + Show(pale));
            yield return new WaitForSeconds(1.5f);
            Check("readouts: the number settles on the model's value", Mathf.Abs(ui.ShownKpis.exposure - target) < 0.5f,
                  $"shown {ui.ShownKpis.exposure:N1}, target {target:N1}");
            Check("paint: the flash fades out after the stroke", flash.vertexCount == 0, $"{flash.vertexCount} vertices");

            // Undo: back to the plan before the last stroke, and Reset all can be undone too.
            float painted = d.Model.TotalExposure();
            d.Model.SaveUndo();
            d.Model.Apply(Intervention.PocketPark, hot, 1f);
            Button(HudStyle.UndoButton).onClick.Invoke();
            Check("undo: the Undo button takes back the last stroke", Mathf.Abs(d.Model.TotalExposure() - painted) < 0.01f &&
                  d.Model.Share(Intervention.PocketPark, hot) == 0f, $"{d.Model.TotalExposure():N1} vs {painted:N1}");
            Button(HudStyle.ResetButton).onClick.Invoke();
            d.Model.Undo();
            Check("undo: Reset all can be undone", Mathf.Abs(d.Model.TotalExposure() - painted) < 0.01f, $"{d.Model.TotalExposure():N1}");
            while (d.Model.Undo()) { }   // earlier tests left steps behind
            Check("undo: with nothing left to undo, Undo does nothing", !d.Model.CanUndo && !d.Model.Undo());
            yield return null;
            Check("undo: the button is greyed out with nothing to undo", !Button(HudStyle.UndoButton).interactable);

            // The selected tool's small label is full-strength dark text on the orange fill.
            brush.Tool = Intervention.Trees;
            yield return null;
            var toolLabel = Button(HudStyle.ToolButtonPrefix + Intervention.Trees).GetComponentInChildren<TextMeshProUGUI>().text;
            Check("tools: the selected tool's sub-label is not dimmed", toolLabel.Contains("<alpha=#FF>") && !toolLabel.Contains("<alpha=#B0>"), toolLabel);
            brush.Tool = Intervention.CoolRoof;
            yield return null;
            Check("tools: the hint says how to paint", Text(HudStyle.ToolHint).Contains("Drag over blocks to paint"));
            Check("controls: the sidebar lists the mouse and key controls",
                  Text(HudStyle.Controls).Contains("RIGHT-DRAG") && Text(HudStyle.Controls).Contains("CTRL+Z"));
            Check("brush: the label counts blocks (radius 1 = 5 blocks)", Text(HudStyle.BrushValue) == "5 blocks", Text(HudStyle.BrushValue));
            d.Model.ResetAll();

            // Heat shimmer: over the hottest tenth of blocks, only in the heat views.
            var shimmer = FindFirstObjectByType<HeatShimmer>();
            yield return null;
            int valid = Enumerable.Range(0, d.Data.BlockCount).Count(d.Model.IsValid);
            int expectedHot = Enumerable.Range(0, d.Data.BlockCount).Count(b => d.Model.IsValid(b) && d.Model.Lst(b) >= shimmer.Threshold);
            Check("shimmer: over the hottest ~10% of blocks", shimmer.HotBlocks == expectedHot &&
                  shimmer.HotBlocks > 0.05f * valid && shimmer.HotBlocks < 0.15f * valid, $"{shimmer.HotBlocks} of {valid}");
            var sheets = Find("HeatShimmer").GetComponent<MeshRenderer>();
            d.SetMode(ViewMode.Materials);
            yield return null;
            Check("shimmer: hidden in the Materials view", !sheets.enabled);
            d.SetMode(ViewMode.Heat);
            yield return null;
            Check("shimmer: shown in the Surface heat view", sheets.enabled);

            // Downlink ticker: real scene sets and the required credits, scrolling.
            string ticker = Text(HudStyle.Footer);
            Check("ticker: lists the Landsat 9 scenes and the Copernicus credit",
                  ticker.Contains("LANDSAT 9 · 32 SCENES") && ticker.Contains("Contains modified Copernicus Sentinel data"),
                  ticker.Substring(0, Mathf.Min(120, ticker.Length)));
            var tickerRt = Find(HudStyle.Footer).GetComponent<RectTransform>();
            float x0 = tickerRt.anchoredPosition.x;
            yield return new WaitForSeconds(0.3f);
            Check("ticker: scrolls", !Mathf.Approximately(x0, tickerRt.anchoredPosition.x), $"{x0:0} → {tickerRt.anchoredPosition.x:0}");

            // Exit next to GLOBE: the first click only asks to confirm, so the app keeps running.
            Check("header: an EXIT button next to GLOBE; one click only asks to confirm",
                  Find(HudStyle.ExitButton) != null &&
                  InvokeAndReturn(() => Button(HudStyle.ExitButton).onClick.Invoke(), () => QuitGuard.Armed));
            QuitGuard.Disarm();

            // Legend title fits now (it used to be cut off), model notes fold out.
            var title = Find(HudStyle.LegendTitle).GetComponent<TextMeshProUGUI>();
            title.ForceMeshUpdate();
            Check("legend: title is not cut off", !title.isTextTruncated && title.text.Contains("typical block"), title.text);
            var notes = Find(HudStyle.ModelPanel);
            Button(HudStyle.ModelButton).onClick.Invoke();
            bool opened = notes.activeSelf;
            Button(HudStyle.ModelButton).onClick.Invoke();
            Check("model notes: the [+] button folds them out and back", opened && !notes.activeSelf);

            // Popup slides in.
            Button(HudStyle.FiguresButton).onClick.Invoke();
            yield return null;
            var card = Find(HudStyle.FigureCard).GetComponent<RectTransform>();
            float y0 = card.anchoredPosition.y;
            yield return new WaitForSeconds(0.45f);
            Check("popup: slides up into place", y0 < -1f && Mathf.Abs(card.anchoredPosition.y) < 0.5f,
                  $"{y0:0.0} → {card.anchoredPosition.y:0.0}");
            Button(HudStyle.FigureClose).onClick.Invoke();

            // Living scene: the sun moves; left alone, the camera drifts.
            var sun = FindFirstObjectByType<SunCycle>().transform;
            var r0 = sun.rotation;
            yield return new WaitForSeconds(0.5f);
            Check("sun: moves across the sky", Quaternion.Angle(r0, sun.rotation) > 0.05f, $"{Quaternion.Angle(r0, sun.rotation):0.000}°");
            var cam = FindFirstObjectByType<OrbitCamera>();
            float waited = 0f;
            while (!cam.Drifting && waited < 12f) { waited += Time.deltaTime; yield return null; }
            Check("camera: drifts by itself when nobody touches it", cam.Drifting, $"waited {waited:0.0} s");
        }

        // ---------- 7. cities ----------

        // Every live city's district file is in the build and is a usable district.
        void CityFiles()
        {
            var bad = new List<string>();
            foreach (var city in CityCatalog.All.Where(c => c.Live && c.Key != "cairo"))
            {
                var text = Resources.Load<TextAsset>("Districts/" + city.Key);
                if (text == null) { bad.Add(city.Name + " missing"); continue; }
                var d = DistrictData.FromJson(text.text);
                int valid = d.blocks.valid.Count(v => v == 1);
                int maps = DistrictUI.CityFigures(city, d).Length;
                if (d.CityName != city.Name || d.name != city.District || valid < 100 || d.buildings.count < 100 ||
                    d.model.r2SpatialCv <= 0f || d.sources == null || d.sources.Length == 0 || !d.HasHeightSources ||
                    maps != (d.HasGrowth ? 6 : 5))
                    bad.Add($"{city.Name} ({d.CityName}/{d.name}, {valid} blocks, {d.buildings.count} buildings, " +
                            $"R² {d.model.r2SpatialCv:0.00}, {maps} analysis maps)");
            }
            Check("cities: every live city's district file and analysis maps load (blocks, buildings, model, sources, heights, maps)",
                  bad.Count == 0, string.Join("; ", bad));
        }

        // Back to the globe, choose Casablanca: its own district, title and data, no Cairo maps.
        IEnumerator SecondCity()
        {
            Button(HudStyle.GlobeButton).onClick.Invoke();
            IntroController intro = null;
            float waited = 0f;
            while (((intro = FindFirstObjectByType<IntroController>()) == null || !intro.ReadyForInput) && waited < 20f)
            { waited += Time.unscaledDeltaTime; yield return null; }
            int index = Array.FindIndex(CityCatalog.All, c => c.Key == "casablanca");
            intro?.ChooseCity(index);
            DistrictView d = null;
            waited = 0f;
            while (((d = FindFirstObjectByType<DistrictView>()) == null || d.Model == null || d.Data.name != "Hay Mohammadi") && waited < 60f)
            { waited += Time.unscaledDeltaTime; yield return null; }
            yield return null;
            yield return null;
            bool loaded = d != null && d.Data.name == "Hay Mohammadi";
            Check("cities: back on the globe, choosing Casablanca opens Hay Mohammadi", loaded,
                  d == null ? "no district" : d.Data.name);
            if (!loaded) yield break;
            var top = Find(HudStyle.TopBar).GetComponentsInChildren<TextMeshProUGUI>().First(t => t.name == "Title").text;
            Check("cities: the top bar and subtitle name the new district and city",
                  top.Contains("HAY MOHAMMADI") && Text(HudStyle.Subtitle).StartsWith("CASABLANCA"), top + " | " + Text(HudStyle.Subtitle));
            d.SetMode(ViewMode.Heat);
            yield return null;
            var mapsButton = Find(HudStyle.FiguresButton);
            string mapsLabel = mapsButton.GetComponentInChildren<TextMeshProUGUI>().text;
            Check("cities: Casablanca has its own analysis maps (2 for Surface heat) and no Growth view",
                  mapsButton.activeSelf && mapsLabel.Contains("(2)") && !Find(HudStyle.ViewButtonPrefix + ViewMode.Growth).activeSelf,
                  mapsLabel);
            Button(HudStyle.FiguresButton).onClick.Invoke();
            yield return null;
            var shown = Find(HudStyle.FigureImage).GetComponent<RawImage>().texture;
            Check("cities: the popup shows Casablanca's map, not Cairo's",
                  shown != null && shown.name == "fig1_study_area" && Text(HudStyle.FigureTitle).StartsWith("Casablanca"),
                  $"{shown?.name} / {Text(HudStyle.FigureTitle)}");
            Button(HudStyle.FigureClose).onClick.Invoke();
            yield return null;
            var notes = Enumerable.Range(0, d.Data.BlockCount).Where(d.Model.IsValid)
                .Select(b => (little: d.Model.TreatableShare(b) < 0.05f, note: DistrictUI.TreatNote(d.Model, d.Data, b))).ToList();
            Check("tooltip: 'little to treat' appears exactly on blocks under 5% treatable",
                  notes.All(n => n.little == n.note.Contains("Little to treat")),
                  $"{notes.Count(n => n.little)} such blocks of {notes.Count}");
            float exposure = d.Model.TotalExposure(false);
            d.Model.ApplyTargetedPlan();
            Check("cities: the targeted plan cuts Casablanca's heat exposure", exposure > 0f && d.Model.TotalExposure() < exposure,
                  $"{exposure:N0} → {d.Model.TotalExposure():N0}");
        }

        // ---------- 6. nothing else changed ----------

        void Unchanged(DistrictView d)
        {
            d.Model.ResetAll();
            float exposure = d.Model.TotalExposure(false);
            Check("unchanged: today's heat exposure is still 6,460 person·°C", Mathf.Abs(exposure - 6460f) < 1f, $"{exposure:N0}");
        }

        // ---------- helpers ----------

        const float FadeHalf = DistrictView.FadeSeconds / 2f;

        static IEnumerator Settle(DistrictView d)
        {
            float t = 0f;
            while (d.Fading && t < 2f) { t += Time.deltaTime; yield return null; }
        }

        static Texture2D Ground(DistrictView d) =>
            (Texture2D)typeof(DistrictView).GetField("_groundTex", BindingFlags.NonPublic | BindingFlags.Instance).GetValue(d);

        static Color MaterialsColor(DistrictView d, int block) =>
            (Color)typeof(DistrictView).GetMethod("GroundColor", BindingFlags.NonPublic | BindingFlags.Instance)
                .Invoke(d, new object[] { block });

        // A block with residents, excess heat and dark roofs, so cool roofs clearly lower its exposure.
        static int HottestBlock(DistrictView d) =>
            Enumerable.Range(0, d.Data.BlockCount)
                .Where(b => d.Model.IsValid(b) && d.Data.blocks.darkRoofFrac[b] > 0.05f)
                .OrderByDescending(b => d.Model.Exposure(b, false) * d.Data.blocks.darkRoofFrac[b])
                .First();

        void Check(string name, bool ok, string detail = "")
        {
            if (ok) { _passed++; Debug.Log($"[SelfTest] PASS {name}"); }
            else { _failed++; _failures.Add(name); Debug.LogWarning($"[SelfTest] FAIL {name}: {detail}"); }
        }

        static GameObject Find(string name) =>
            Resources.FindObjectsOfTypeAll<Transform>().FirstOrDefault(t => t.name == name && t.gameObject.scene.IsValid())?.gameObject;

        static Button Button(string name) => Find(name).GetComponent<Button>();
        static string Text(string name) => Find(name).GetComponent<TextMeshProUGUI>().text;
        static string ExposureSub() =>
            Find(HudStyle.KpiExposure).transform.Find(HudStyle.KpiSub).GetComponent<TextMeshProUGUI>().text;

        static bool Same(List<int> a, int[] b) => a.Count == b.Length && !a.Except(b).Any();
        static bool Near(Color a, Color b) => Mathf.Abs(a.r - b.r) < 0.02f && Mathf.Abs(a.g - b.g) < 0.02f && Mathf.Abs(a.b - b.b) < 0.02f;
        static Color Hex(int rgb) => new Color(((rgb >> 16) & 255) / 255f, ((rgb >> 8) & 255) / 255f, (rgb & 255) / 255f);
        static string Show(Color c) => "#" + ColorUtility.ToHtmlStringRGB(c);
    }
}
