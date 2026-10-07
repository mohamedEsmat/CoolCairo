using System.Collections.Generic;
using System.Linq;
using TMPro;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.SceneManagement;
using UnityEngine.UI;

namespace CoolCairo
{
    // Behaviour for the district HUD built by HudBuilder (elements looked up by HudStyle names).
    // Every number shown comes from district.json (analysis notebooks) or the live InterventionModel.
    public class DistrictUI : MonoBehaviour
    {
        [SerializeField] DistrictView district;
        [SerializeField] InterventionBrush brush;
        [SerializeField] AnalysisFigure[] figures;   // the analysis maps per view (ProjectSetup)

        // True while the mouse is over any HUD element; the brush and camera ignore input then.
        public static bool PointerOverUI =>
            EventSystem.current != null && EventSystem.current.IsPointerOverGameObject();

        readonly Dictionary<ViewMode, Button> _viewButtons = new Dictionary<ViewMode, Button>();
        readonly Dictionary<Intervention, Button> _toolButtons = new Dictionary<Intervention, Button>();
        readonly Dictionary<HeatPalette, Button> _paletteButtons = new Dictionary<HeatPalette, Button>();
        TextMeshProUGUI _viewHint, _toolHint, _brushValue, _legendTitle, _legendMin, _legendMax;
        TextMeshProUGUI _deltaValue, _deltaSub, _exposureValue, _exposureSub, _residentsValue, _residentsSub;
        TextMeshProUGUI _tooltipTitle, _tooltipBody;
        RawImage _legendRamp;
        GameObject _legendScale, _legendSwatches, _riskKeys, _growthKeys, _legendPalettes;
        RectTransform _tooltip, _canvas;
        Texture2D _rampTex;
        ViewMode _shownMode = (ViewMode)(-1);
        HeatPalette _shownPalette = (HeatPalette)(-1);
        Intervention _shownTool = (Intervention)(-1);

        // Analysis maps popup
        Button _figuresButton, _figurePrev, _figureNext;
        GameObject _figurePopup;
        RawImage _figureImage;
        AspectRatioFitter _figureFit;
        TextMeshProUGUI _figureTitle, _figureCount, _figureCaption, _figuresButtonLabel;
        List<AnalysisFigure> _figuresShown = new List<AnalysisFigure>();
        int _figureIndex;

        void Start()
        {
            _canvas = (RectTransform)transform;
            foreach (ViewMode mode in System.Enum.GetValues(typeof(ViewMode)))
            {
                var b = Find<Button>(HudStyle.ViewButtonPrefix + mode);
                _viewButtons[mode] = b;
                b.onClick.AddListener(() => district.SetMode(mode));
            }
            // A district exported without growth data has no Growth view.
            _viewButtons[ViewMode.Growth].gameObject.SetActive(district.Data.HasGrowth);
            foreach (Intervention tool in System.Enum.GetValues(typeof(Intervention)))
            {
                var b = Find<Button>(HudStyle.ToolButtonPrefix + tool);
                _toolButtons[tool] = b;
                b.onClick.AddListener(() => brush.Tool = tool);
            }
            foreach (HeatPalette palette in System.Enum.GetValues(typeof(HeatPalette)))
            {
                var b = Find<Button>(HudStyle.PaletteButtonPrefix + palette);
                _paletteButtons[palette] = b;
                b.onClick.AddListener(() => district.SetPalette(palette));
            }
            _figuresButton = Find<Button>(HudStyle.FiguresButton);
            _figuresButtonLabel = _figuresButton.GetComponentInChildren<TextMeshProUGUI>();
            _figuresButton.onClick.AddListener(OpenFigures);
            _figurePopup = Find<RectTransform>(HudStyle.FigurePopup).gameObject;
            _figureImage = Find<RawImage>(HudStyle.FigureImage);
            _figureFit = _figureImage.GetComponent<AspectRatioFitter>();
            _figureTitle = Find<TextMeshProUGUI>(HudStyle.FigureTitle);
            _figureCount = Find<TextMeshProUGUI>(HudStyle.FigureCount);
            _figureCaption = Find<TextMeshProUGUI>(HudStyle.FigureCaption);
            _figurePrev = Find<Button>(HudStyle.FigurePrev);
            _figureNext = Find<Button>(HudStyle.FigureNext);
            _figurePrev.onClick.AddListener(() => ShowFigure(_figureIndex - 1));
            _figureNext.onClick.AddListener(() => ShowFigure(_figureIndex + 1));
            Find<Button>(HudStyle.FigureClose).onClick.AddListener(CloseFigures);
            _figurePopup.SetActive(false);
            Find<Button>(HudStyle.GlobeButton).onClick.AddListener(() => SceneManager.LoadScene(0));
            Find<Button>(HudStyle.ResetButton).onClick.AddListener(() => district.Model.ResetAll());
            var slider = Find<Slider>(HudStyle.BrushSlider);
            slider.SetValueWithoutNotify(brush.Radius);
            slider.onValueChanged.AddListener(v => { brush.Radius = Mathf.RoundToInt(v); ShowBrush(); });

            _viewHint = Find<TextMeshProUGUI>(HudStyle.ViewHint);
            _toolHint = Find<TextMeshProUGUI>(HudStyle.ToolHint);
            _brushValue = Find<TextMeshProUGUI>(HudStyle.BrushValue);
            (_deltaValue, _deltaSub) = Kpi(HudStyle.KpiDelta);
            (_exposureValue, _exposureSub) = Kpi(HudStyle.KpiExposure);
            (_residentsValue, _residentsSub) = Kpi(HudStyle.KpiResidents);
            // Values shrink to fit the card rather than being cut off ("44.8 → 44.0 °C").
            foreach (var value in new[] { _deltaValue, _exposureValue, _residentsValue })
            {
                value.enableAutoSizing = true;
                value.fontSizeMin = 18;
                value.fontSizeMax = 32;
            }
            _legendTitle = Find<TextMeshProUGUI>(HudStyle.LegendTitle);
            _legendMin = Find<TextMeshProUGUI>(HudStyle.LegendMin);
            _legendMax = Find<TextMeshProUGUI>(HudStyle.LegendMax);
            _legendRamp = Find<RawImage>(HudStyle.LegendRamp);
            _legendScale = Find<RectTransform>(HudStyle.LegendScale).gameObject;
            _legendSwatches = Find<RectTransform>(HudStyle.LegendSwatches).gameObject;
            _legendPalettes = Find<RectTransform>(HudStyle.LegendPalettes).gameObject;
            _tooltip = Find<RectTransform>(HudStyle.Tooltip);
            _tooltipTitle = Find<TextMeshProUGUI>(HudStyle.TooltipTitle);
            _tooltipBody = Find<TextMeshProUGUI>(HudStyle.TooltipBody);
            _tooltipBody.richText = true;

            _rampTex = new Texture2D(256, 1, TextureFormat.RGBA32, false) { wrapMode = TextureWrapMode.Clamp };
            _legendRamp.texture = _rampTex;
            BuildSwatches();
            _riskKeys = BuildKeys("RiskKeys", _legendScale.transform.GetSiblingIndex() + 1,
                                  ("No excess heat (at or below typical)", DistrictView.NoExcessHeat),
                                  ("No residents", DistrictView.NoResidents));
            _growthKeys = BuildKeys("GrowthKeys", _legendScale.transform.GetSiblingIndex() + 1,
                                    district.GrowthLegend().ToArray());
            Find<TextMeshProUGUI>(HudStyle.ModelText).text = ModelSummary();
            Find<TextMeshProUGUI>(HudStyle.Footer).text = Credits();

            district.Model.Changed += RefreshKpis;
            ShowBrush();
            RefreshKpis();
        }

        void OnDestroy()
        {
            if (district != null && district.Model != null) district.Model.Changed -= RefreshKpis;
        }

        void Update()
        {
            // Mode and tool can also change from code (e.g. the soak test), so poll them.
            if (district.Mode != _shownMode || district.Palette != _shownPalette) ShowView(district.Mode);
            if (brush.Tool != _shownTool) ShowTool(brush.Tool);
            if (_figurePopup.activeSelf)
            {
                if (Input.GetKeyDown(KeyCode.Escape)) CloseFigures();
                if (Input.GetKeyDown(KeyCode.RightArrow)) ShowFigure(_figureIndex + 1);
                if (Input.GetKeyDown(KeyCode.LeftArrow)) ShowFigure(_figureIndex - 1);
            }
            UpdateTooltip();
        }

        // ---------- sidebar ----------

        void ShowView(ViewMode mode)
        {
            _shownMode = mode;
            _shownPalette = district.Palette;
            foreach (var kv in _viewButtons) Highlight(kv.Value, kv.Key == mode);
            foreach (var kv in _paletteButtons) Highlight(kv.Value, kv.Key == district.Palette);
            var m = district.Data.model;
            _viewHint.text = mode switch
            {
                ViewMode.Materials => "What surfaces are made of, per 90 m block (Sentinel-2, summer 2023–25): dark vs pale roofs, asphalt, sand and greenery.",
                ViewMode.Heat => "Land surface temperature per 90 m block: median of summer 2023–25 Landsat 8/9 scenes. Surface, not air, temperature.",
                ViewMode.Growth => GrowthHint(),
                _ => $"Heat exposure = residents × °C above {m.heatReferenceC:0.0} °C, the typical east-Cairo block. Residents: WorldPop 2024.",
            };
            ShowLegend(mode);

            int count = FiguresFor(mode).Count;
            _figuresButton.gameObject.SetActive(count > 0);
            _figuresButtonLabel.text = count == 1 ? "Analysis map for this view  ›" : $"Analysis maps for this view ({count})  ›";
        }

        // ---------- analysis maps ----------

        List<AnalysisFigure> FiguresFor(ViewMode mode) =>
            (figures ?? new AnalysisFigure[0]).Where(f => f.view == mode && f.image != null).ToList();

        void OpenFigures()
        {
            _figuresShown = FiguresFor(district.Mode);
            if (_figuresShown.Count == 0) return;
            _figurePopup.SetActive(true);
            ShowFigure(0);
        }

        void CloseFigures() => _figurePopup.SetActive(false);

        void ShowFigure(int index)
        {
            if (_figuresShown.Count == 0) return;
            _figureIndex = Mathf.Clamp(index, 0, _figuresShown.Count - 1);
            var f = _figuresShown[_figureIndex];
            _figureImage.texture = f.image;
            _figureFit.aspectRatio = f.image.width / (float)f.image.height;   // keep the figure's shape
            _figureTitle.text = f.title;
            _figureCaption.text = f.caption;
            _figureCount.text = $"{_figureIndex + 1} / {_figuresShown.Count}";
            _figurePrev.interactable = _figureIndex > 0;
            _figureNext.interactable = _figureIndex < _figuresShown.Count - 1;
        }

        string GrowthHint()
        {
            var g = district.Data.growth;
            if (g == null || g.available != 1) return "";
            return $"Building cover per block, {g.firstYear} → {g.lastYear} (Google Open Buildings Temporal): " +
                   $"{g.builtFirstKm2:0.00} → {g.builtLastKm2:0.00} km²; {g.newBlocks} new, {g.denserBlocks} denser blocks.";
        }

        void ShowTool(Intervention tool)
        {
            _shownTool = tool;
            foreach (var kv in _toolButtons) Highlight(kv.Value, kv.Key == tool);
            var m = district.Data.model;
            var model = district.Model;
            _toolHint.text = tool switch
            {
                Intervention.CoolRoof =>
                    $"Coat every roof in a block white. Per unit of area coated: {Minus(m.coolRoofDarkDeltaC)} °C on dark roofs, {Minus(m.coolRoofPaleDeltaC)} °C on pale roofs (published values).",
                Intervention.Trees =>
                    $"Plant street trees on up to {model.TreeMaxShare:P0} of a block's dark ground. Effect estimated from our own data.",
                Intervention.CoolPavement =>
                    $"Coat asphalt and dark paving with reflective paint: {Minus(m.coolPavementDeltaC)} °C per unit of area coated (published values, conservative).",
                _ =>
                    $"Turn up to {model.ParkMaxShare:P0} of a block's bare sand into a small park: {Minus(m.pocketParkDeltaC)} °C per unit of area greened (our own data).",
            };
        }

        void ShowBrush() => _brushValue.text = brush.Radius == 0 ? "1 block" : $"radius {brush.Radius} blocks";

        static void Highlight(Button b, bool selected)
        {
            b.targetGraphic.color = selected ? HudStyle.Accent : HudStyle.Button;
            var label = b.GetComponentInChildren<TextMeshProUGUI>();
            label.color = selected ? HudStyle.AccentText : HudStyle.Text;
            label.fontStyle = selected ? FontStyles.Bold : FontStyles.Normal;
        }

        // ---------- result cards ----------

        void RefreshKpis()
        {
            var model = district.Model;
            // Before -> after, so the change reads as real temperatures, not an abstract delta.
            float before = model.MeanLst(false), after = model.MeanLst(), delta = after - before;
            int blocks = Enumerable.Range(0, district.Data.BlockCount).Count(model.IsValid);
            bool changed = delta < -0.005f;
            _deltaValue.text = changed ? $"{before:0.0} → {after:0.0} °C" : $"{before:0.0} °C";
            _deltaValue.color = changed ? HudStyle.Good : HudStyle.Text;
            _deltaSub.text = changed ? $"{Minus(delta, "0.00")} °C · average of {blocks} blocks"
                                     : $"today · average of {blocks} blocks";

            float baseRisk = model.TotalExposure(false), nowRisk = model.TotalExposure();
            float pct = baseRisk > 0f ? 100f * (nowRisk - baseRisk) / baseRisk : 0f;
            _exposureValue.text = $"{nowRisk:N0}";
            _exposureValue.color = pct < -0.5f ? HudStyle.Good : HudStyle.Text;
            _exposureSub.text = $"person·°C · {Minus(pct, "0")}% vs today";

            _residentsValue.text = $"{model.ResidentsInCooledBlocks():N0}";
            _residentsValue.color = model.ResidentsInCooledBlocks() > 0f ? HudStyle.Good : HudStyle.Text;
            _residentsSub.text = $"of {model.TotalResidents():N0} residents";
        }

        // Proper minus sign (U+2212) and an explicit plus for positive changes.
        static string Minus(float v, string format = "0.0") =>
            v < 0f ? "−" + (-v).ToString(format) : v > 0f ? "+" + v.ToString(format) : v.ToString(format);

        (TextMeshProUGUI value, TextMeshProUGUI sub) Kpi(string card)
        {
            var root = Find<RectTransform>(card);
            return (FindIn<TextMeshProUGUI>(root, HudStyle.KpiValue), FindIn<TextMeshProUGUI>(root, HudStyle.KpiSub));
        }

        // ---------- legend ----------

        void ShowLegend(ViewMode mode)
        {
            bool scale = mode == ViewMode.Heat || mode == ViewMode.Risk;
            _legendScale.SetActive(scale);
            _legendSwatches.SetActive(mode == ViewMode.Materials);
            _riskKeys.SetActive(mode == ViewMode.Risk);
            _growthKeys.SetActive(mode == ViewMode.Growth);
            _legendPalettes.SetActive(mode == ViewMode.Heat);
            if (mode == ViewMode.Materials)
            {
                _legendTitle.text = "Surface materials (share per block)";
                return;
            }
            if (mode == ViewMode.Growth)
            {
                var g = district.Data.growth;
                _legendTitle.text = $"Urban growth {g.firstYear}–{g.lastYear}";
                return;
            }
            var px = new Color[_rampTex.width];
            for (int i = 0; i < px.Length; i++)
            {
                float t = i / (px.Length - 1f);
                px[i] = mode == ViewMode.Heat
                    ? district.HeatColor(Mathf.Lerp(district.HeatMin, district.HeatMax, t))
                    : district.RiskColor(t * district.RiskMax);
            }
            _rampTex.SetPixels(px);
            _rampTex.Apply(false);
            if (mode == ViewMode.Heat)
            {
                _legendTitle.text = district.Palette == HeatPalette.Report
                    ? $"Land surface temperature (grey = typical block, {district.Data.model.heatReferenceC:0.0} °C)"
                    : "Land surface temperature";
                _legendMin.text = $"{district.HeatMin:0} °C";
                _legendMax.text = $"{district.HeatMax:0} °C";
            }
            else
            {
                _legendTitle.text = "Heat exposure (person·°C per block)";
                _legendMin.text = "> 0";
                _legendMax.text = $"{district.RiskMax:N0}+";
            }
        }

        void BuildSwatches()
        {
            foreach (var (label, color) in district.MaterialLegend()) SwatchRow(_legendSwatches.transform, label, color);
        }

        // Extra legend rows next to the colour scale (heat-risk view: zero-risk / no-residents).
        GameObject BuildKeys(string name, int siblingIndex, params (string label, Color color)[] keys)
        {
            var box = new GameObject(name, typeof(RectTransform), typeof(VerticalLayoutGroup));
            box.transform.SetParent(_legendSwatches.transform.parent, false);
            box.transform.SetSiblingIndex(siblingIndex);
            var v = box.GetComponent<VerticalLayoutGroup>();
            v.spacing = 4;
            v.childControlWidth = v.childControlHeight = true;
            v.childForceExpandHeight = false;
            foreach (var (label, color) in keys) SwatchRow(box.transform, label, color);
            return box;
        }

        void SwatchRow(Transform parent, string label, Color color)
        {
            var font = _legendTitle.font;
            var row = new GameObject(label, typeof(RectTransform), typeof(HorizontalLayoutGroup), typeof(LayoutElement));
            row.transform.SetParent(parent, false);
            row.GetComponent<LayoutElement>().preferredHeight = 18;
            var h = row.GetComponent<HorizontalLayoutGroup>();
            h.spacing = 8;
            h.childControlWidth = h.childControlHeight = true;
            h.childForceExpandWidth = false;

            var sw = new GameObject("Swatch", typeof(RectTransform), typeof(Image), typeof(LayoutElement));
            sw.transform.SetParent(row.transform, false);
            sw.GetComponent<Image>().color = color;
            sw.GetComponent<Image>().raycastTarget = false;
            var le = sw.GetComponent<LayoutElement>();
            le.preferredWidth = le.minWidth = 14;

            var text = new GameObject("Label", typeof(RectTransform), typeof(TextMeshProUGUI));
            text.transform.SetParent(row.transform, false);
            var t = text.GetComponent<TextMeshProUGUI>();
            t.font = font;
            t.fontSize = 12;
            t.color = HudStyle.Muted;
            t.text = label;
            t.raycastTarget = false;
            t.alignment = TextAlignmentOptions.MidlineLeft;
        }

        // ---------- hover card ----------

        void UpdateTooltip()
        {
            int h = brush.HoverBlock;
            var model = district.Model;
            bool show = h >= 0 && model.IsValid(h) && !PointerOverUI;
            if (_tooltip.gameObject.activeSelf != show) _tooltip.gameObject.SetActive(show);
            if (!show) return;

            var b = district.Data.blocks;
            float t0 = model.BaselineLst(h), t1 = model.Lst(h);
            float e0 = model.Exposure(h, false), e1 = model.Exposure(h);
            string temp = t1 < t0 - 0.01f ? $"{t0:0.0} °C → <color=#4CD08A>{t1:0.0} °C</color>" : $"{t0:0.0} °C";
            string expo = e1 < e0 - 0.5f ? $"{e0:N0} → <color=#4CD08A>{e1:N0}</color>" : $"{e0:N0}";
            _tooltipTitle.text = $"Block {h}";
            _tooltipBody.text =
                $"Surface temperature  <color=#E8EEF6>{temp}</color>\n" +
                $"Residents  <color=#E8EEF6>{model.Residents(h):N0}</color>  ·  heat exposure <color=#E8EEF6>{expo}</color> person·°C\n" +
                $"Roofs: {b.darkRoofFrac[h]:P0} dark, {b.paleRoofFrac[h]:P0} pale of block area\n" +
                $"Ground: {b.darkGroundFrac[h]:P0} dark, {b.soilFrac[h]:P0} sand, {b.vegFrac[h]:P0} green";
            if (district.Data.HasGrowth && b.builtFirst[h] >= 0f && b.builtLast[h] >= 0f)
                _tooltipBody.text += $"\nBuilding cover {district.Data.growth.firstYear} → {district.Data.growth.lastYear}: " +
                                     $"{b.builtFirst[h]:P0} → {b.builtLast[h]:P0}";

            // Follow the mouse, flipping sides near the screen edges.
            RectTransformUtility.ScreenPointToLocalPointInRectangle(_canvas, Input.mousePosition, null, out var local);
            var size = _canvas.rect.size;
            var pos = local + size / 2f + new Vector2(18f, -18f);
            LayoutRebuilder.ForceRebuildLayoutImmediate(_tooltip);
            var tip = _tooltip.rect.size;
            if (pos.x + tip.x > size.x - 8f) pos.x -= tip.x + 36f;
            if (pos.y - tip.y < 8f) pos.y += tip.y + 36f;
            _tooltip.anchoredPosition = pos;
        }

        // ---------- texts from district.json ----------

        string ModelSummary()
        {
            var d = district.Data;
            var m = d.model;
            string text = $"Block-level (90 m) land surface temperature. Heat model: spatial cross-validated R² {m.r2SpatialCv:0.00}, " +
                          $"error ±{m.maeSpatialCv:0.0} °C, {m.nBlocks:N0} urban blocks.";
            var h = d.hyperspectral;
            if (h != null && h.available == 1)
                text += $"\nHyperspectral EnMAP ({h.acquired}) explains heat at R² {h.r2Hyperspectral:0.00} vs {h.r2Multispectral:0.00} with Sentinel-2.";
            // Satellites measure surfaces, not air; give the air effect only as a cited city-wide range.
            text += "\n<b>Surface ≠ air temperature.</b> Studies suggest city-wide cool roofs lower air temperature by " +
                    "~0.1–0.33 °C per +0.1 roof albedo (Santamouris 2014, cited in Wang et al. 2020); the effect on air " +
                    "is smaller than on surfaces and spreads beyond the district.";
            return text;
        }

        string Credits()
        {
            var parts = new List<string>
            {
                "Landsat 8/9 surface temperature: USGS",
                "Contains modified Copernicus Sentinel data [2023–2025]",
            };
            var h = district.Data.hyperspectral;
            if (h != null && h.available == 1) parts.Add(h.attribution);
            parts.Add("Residents: WorldPop 2024 (CC BY 4.0)");
            parts.Add("Buildings and growth: © OpenStreetMap contributors, Google Open Buildings 2.5D Temporal (CC BY 4.0)");
            parts.Add("Data access: Microsoft Planetary Computer, DLR EOC Geoservice");
            return string.Join("  ·  ", parts);
        }

        // ---------- lookup ----------

        T Find<T>(string name) where T : Component => FindIn<T>(transform, name);

        static T FindIn<T>(Transform root, string name) where T : Component
        {
            foreach (var t in root.GetComponentsInChildren<Transform>(true))
                if (t.name == name)
                {
                    var c = t.GetComponent<T>();
                    if (c != null) return c;
                }
            Debug.LogError($"HUD element '{name}' ({typeof(T).Name}) not found; rebuild the scene with CoolCairo/Setup.");
            return null;
        }
    }
}
