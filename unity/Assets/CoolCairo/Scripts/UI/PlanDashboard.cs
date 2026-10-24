using System.Collections.Generic;
using System.Linq;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace CoolCairo
{
    // "Plan results" panel, opened from the button under the result cards (or the P key).
    // Two pages:
    //   RESULTS      heat exposure removed so far (the report's −74% when the targeted plan is on),
    //                a one-click targeted plan, each measure's share of the removal, and the plan
    //                against one measure in every block;
    //   RISKIEST 10  the blocks with the most heat exposure right now; a click flies there.
    // Built at runtime from the HUD's own sprites, fonts and colours, so Main.unity needs no rebuild.
    // Every number comes from the live InterventionModel (the same arithmetic as the analysis).
    public class PlanDashboard : MonoBehaviour
    {
        public const string ToggleName = "PlanToggle", PanelName = "PlanPanel", TargetedName = "PlanTargeted";
        public const string TabResults = "PlanTab_Results", TabRiskiest = "PlanTab_Riskiest";
        public const string HeadlineName = "PlanHeadline", RiskRowPrefix = "PlanRisk_";

        static readonly string[] MeasureNames = { "Cool roofs", "Street trees", "Cool pavements", "Pocket parks" };
        static readonly Intervention[] Kinds =
            { Intervention.CoolRoof, Intervention.Trees, Intervention.CoolPavement, Intervention.PocketPark };
        const int RiskRows = 10;
        const float PanelWidth = 360f;

        DistrictView _district;
        OrbitCamera _camera;
        BlockHighlight _highlight;
        Sprite _solid, _frame, _bracket;
        TMP_FontAsset _mono, _sans;

        RectTransform _panel, _resultsPage, _riskPage;
        CanvasGroup _panelGroup;
        Button _toggle, _tabResults, _tabRiskiest;
        TextMeshProUGUI _toggleLabel, _headline, _headlineSub, _treated;
        readonly (RectTransform fill, TextMeshProUGUI value)[] _measureBars = new (RectTransform, TextMeshProUGUI)[4];
        readonly (RectTransform fill, TextMeshProUGUI value)[] _compareBars = new (RectTransform, TextMeshProUGUI)[5];
        readonly List<(Button button, TextMeshProUGUI text)> _riskRows = new List<(Button, TextMeshProUGUI)>();
        readonly List<int> _riskBlocks = new List<int>();
        float[] _everywherePct;
        bool _riskiestShown;
        float _fade;

        public bool Open => _panel != null && _panel.gameObject.activeSelf;
        public float RemovedPct { get; private set; }   // shown in the headline (the self-test reads it)
        public IReadOnlyList<int> RiskBlocksShown => _riskBlocks;

        public void Init(DistrictView district, TMP_FontAsset mono, TMP_FontAsset sans, RectTransform styleSource)
        {
            _district = district;
            _mono = mono;
            _sans = sans;
            _solid = styleSource.GetComponent<Image>().sprite;
            _frame = styleSource.Find("Frame").GetComponent<Image>().sprite;
            _bracket = styleSource.GetComponentsInChildren<Image>(true).First(i => i.name == "Bracket").sprite;
            _camera = FindFirstObjectByType<OrbitCamera>();
            _highlight = FindFirstObjectByType<BlockHighlight>();
            Build();
            district.Model.Changed += Refresh;
            Refresh();
            SetOpen(false);
        }

        void OnDestroy()
        {
            if (_district != null && _district.Model != null) _district.Model.Changed -= Refresh;
        }

        void Update()
        {
            if (Input.GetKeyDown(KeyCode.P)) SetOpen(!Open);
            if (_fade < 1f && _panelGroup != null)
            {
                _fade = Mathf.Min(1f, _fade + Time.unscaledDeltaTime / 0.18f);
                _panelGroup.alpha = _fade;
            }
        }

        public void SetOpen(bool open)
        {
            _panel.gameObject.SetActive(open);
            _toggleLabel.text = open ? "▾  PLAN RESULTS" : "▸  PLAN RESULTS";
            _toggle.targetGraphic.color = open ? HudStyle.Accent : HudStyle.Button;
            _toggleLabel.color = open ? HudStyle.AccentText : HudStyle.Text;
            if (open)
            {
                _fade = 0f;
                _panelGroup.alpha = 0f;
                Refresh();
            }
        }

        public void ShowRiskiest(bool riskiest)
        {
            _riskiestShown = riskiest;
            _resultsPage.gameObject.SetActive(!riskiest);
            _riskPage.gameObject.SetActive(riskiest);
            Tab(_tabResults, !riskiest);
            Tab(_tabRiskiest, riskiest);
            Refresh();
        }

        // Camera to a block and a short outline on it.
        public void FlyTo(int block)
        {
            var d = _district.Data;
            float s = d.blockSize;
            _camera?.FocusOn(new Vector3((block % d.cols + 0.5f) * s, 0f, (block / d.cols + 0.5f) * s));
            _highlight?.Focus(block);
        }

        // ---------- numbers ----------

        void Refresh()
        {
            if (_panel == null || !_panel.gameObject.activeSelf) return;
            var model = _district.Model;
            float before = model.TotalExposure(false), now = model.TotalExposure();
            RemovedPct = before > 0f ? 100f * (before - now) / before : 0f;
            bool plan = model.HasPlan;
            _headline.text = plan ? $"−{RemovedPct:0}%" : "0%";
            _headline.color = RemovedPct > 0.5f ? HudStyle.Good : HudStyle.Text;
            _headlineSub.text = $"of today's heat exposure\n{before:N0} → {now:N0} person·°C";
            int treated = model.TreatedBlocks();
            _treated.text = plan
                ? $"{treated} {(treated == 1 ? "block" : "blocks")} treated · {model.ResidentsInCooledBlocks():N0} residents in cooled blocks"
                : "No plan yet: paint measures, or use the targeted plan above.";

            var removed = model.ExposureRemovedByMeasure();
            for (int k = 0; k < Kinds.Length; k++)
            {
                float pct = before > 0f ? 100f * removed[k] / before : 0f;
                Bar(_measureBars[k], pct / 100f, removed[k] > 0.5f ? $"−{removed[k]:N0}" : "–");
            }

            if (_everywherePct == null)   // fixed: depends only on today's data
                _everywherePct = Kinds.Select(k =>
                    before > 0f ? 100f * (before - model.ExposureIfEverywhere(k)) / before : 0f).ToArray();
            for (int k = 0; k < Kinds.Length; k++) Bar(_compareBars[k], _everywherePct[k] / 100f, $"−{_everywherePct[k]:0}%");
            Bar(_compareBars[4], RemovedPct / 100f, plan ? $"−{RemovedPct:0}%" : "0%");

            if (_riskiestShown) RefreshRiskiest();
        }

        void RefreshRiskiest()
        {
            var model = _district.Model;
            var d = _district.Data;
            _riskBlocks.Clear();
            _riskBlocks.AddRange(model.RiskiestBlocks(RiskRows));
            for (int i = 0; i < _riskRows.Count; i++)
            {
                bool has = i < _riskBlocks.Count;
                _riskRows[i].button.gameObject.SetActive(has);
                if (!has) continue;
                int b = _riskBlocks[i];
                _riskRows[i].text.text =
                    $"<color=#4FD6FF>{i + 1:00}</color>  R{b / d.cols:00}·C{b % d.cols:00}" +
                    $"   <color=#E6F1FF>{model.Exposure(b):N0}</color> person·°C" +
                    $"   {model.Lst(b):0.0} °C   {model.Residents(b):N0} res.";
            }
        }

        static void Bar((RectTransform fill, TextMeshProUGUI value) bar, float fraction, string value)
        {
            bar.fill.anchorMax = new Vector2(Mathf.Clamp01(fraction), 1f);
            bar.value.text = value;
        }

        // ---------- building ----------

        void Build()
        {
            var root = (RectTransform)transform;

            // Toggle under the result cards, right-aligned with them.
            _toggle = MakeButton(root, ToggleName, "▸  PLAN RESULTS", 12, out _toggleLabel);
            var trt = (RectTransform)_toggle.transform;
            trt.anchorMin = trt.anchorMax = trt.pivot = new Vector2(1, 1);
            trt.anchoredPosition = new Vector2(-16, -16 - 56 - 14 - 112 - 10);
            trt.sizeDelta = new Vector2(190, 30);
            _toggle.onClick.AddListener(() => SetOpen(!Open));

            _panel = Glass(root, PanelName);
            _panel.anchorMin = _panel.anchorMax = _panel.pivot = new Vector2(1, 1);
            _panel.anchoredPosition = new Vector2(-16, -16 - 56 - 14 - 112 - 10 - 30 - 8);
            _panel.sizeDelta = new Vector2(PanelWidth, 0);
            _panelGroup = _panel.gameObject.AddComponent<CanvasGroup>();
            Column(_panel.gameObject, new RectOffset(16, 16, 12, 14), 8, fit: true);

            var tabs = Row(_panel, "PlanTabs", 26, 6);
            _tabResults = MakeButton(tabs, TabResults, "Results", 11, out _);
            _tabRiskiest = MakeButton(tabs, TabRiskiest, "Riskiest 10", 11, out _);
            Flex(_tabResults.gameObject);
            Flex(_tabRiskiest.gameObject);
            _tabResults.onClick.AddListener(() => ShowRiskiest(false));
            _tabRiskiest.onClick.AddListener(() => ShowRiskiest(true));

            BuildResults();
            BuildRiskiest();
            ShowRiskiest(false);

            // Under the popup and the hover card, which stay on top of everything.
            foreach (var top in new[] { HudStyle.FigurePopup, HudStyle.Tooltip })
            {
                var t = root.Find(top);
                if (t != null) t.SetAsLastSibling();
            }
        }

        void BuildResults()
        {
            _resultsPage = Page("PlanResults");
            Section(_resultsPage, "⌜ HEAT EXPOSURE REMOVED ⌝");
            var head = Row(_resultsPage, "PlanHead", 44, 12);
            _headline = Label(head, HeadlineName, "0%", 34, HudStyle.Text, mono: true, bold: true);
            Fixed(_headline.gameObject, 112, 44);
            _headlineSub = Label(head, "PlanHeadSub", "", 11, HudStyle.Muted, mono: true, wrap: true);
            Flex(_headlineSub.gameObject);
            _treated = Label(_resultsPage, "PlanTreated", "", 11, HudStyle.Muted, wrap: true);

            var targeted = MakeButton(_resultsPage, TargetedName, "▶  Targeted plan: roofs + parks on the riskiest third", 10, out var tl);
            tl.fontStyle = FontStyles.Normal;
            Fixed(targeted.gameObject, -1, 28);
            targeted.onClick.AddListener(() => _district.Model.ApplyTargetedPlan());

            Divider(_resultsPage);
            Section(_resultsPage, "YOUR PLAN · EXPOSURE REMOVED BY MEASURE");
            for (int k = 0; k < Kinds.Length; k++)
                _measureBars[k] = BarRow(_resultsPage, "PlanMeasure_" + Kinds[k], MeasureNames[k],
                                         TreatmentOverlay.Measures.First(m => m.kind == Kinds[k]).color);   // the ring colours

            Divider(_resultsPage);
            Section(_resultsPage, "ONE MEASURE EVERYWHERE vs YOUR PLAN");
            for (int k = 0; k < Kinds.Length; k++)
                _compareBars[k] = BarRow(_resultsPage, "PlanCompare_" + Kinds[k], MeasureNames[k], HudStyle.Chrome);
            _compareBars[4] = BarRow(_resultsPage, "PlanCompare_Plan", "Your plan", HudStyle.Good, bold: true);
        }

        void BuildRiskiest()
        {
            _riskPage = Page("PlanRiskiest");
            Section(_riskPage, "RISKIEST BLOCKS NOW · CLICK TO FLY THERE");
            for (int i = 0; i < RiskRows; i++)
            {
                int row = i;
                var b = MakeButton(_riskPage, RiskRowPrefix + i, "", 11, out var text);
                text.fontStyle = FontStyles.Normal;
                text.alignment = TextAlignmentOptions.MidlineLeft;
                text.richText = true;
                text.characterSpacing = 0;
                Fixed(b.gameObject, -1, 24);
                b.onClick.AddListener(() => { if (row < _riskBlocks.Count) FlyTo(_riskBlocks[row]); });
                _riskRows.Add((b, text));
            }
            Label(_riskPage, "PlanRiskNote", "Ranked by heat exposure (residents × °C above the typical block). " +
                                             "The list updates as you paint.", 10, HudStyle.Muted, wrap: true);
        }

        (RectTransform, TextMeshProUGUI) BarRow(Transform parent, string name, string label, Color color, bool bold = false)
        {
            var row = Row(parent, name, 16, 8);
            var l = Label(row, "Label", label, 11, bold ? HudStyle.Text : HudStyle.Muted, bold: bold);
            Fixed(l.gameObject, 100, 16);
            var track = Img(row, "Track", HudStyle.Track);
            Flex(track.gameObject);
            var fill = Img(track.transform, "Fill", color);
            var frt = fill.rectTransform;
            frt.anchorMin = Vector2.zero;
            frt.anchorMax = new Vector2(0f, 1f);
            frt.offsetMin = frt.offsetMax = Vector2.zero;
            var v = Label(row, "Value", "", 11, bold ? HudStyle.Good : HudStyle.Text, mono: true, bold: bold,
                          align: TextAlignmentOptions.MidlineRight);
            Fixed(v.gameObject, 62, 16);
            return (frt, v);
        }

        RectTransform Page(string name)
        {
            var rt = new GameObject(name, typeof(RectTransform)).GetComponent<RectTransform>();
            rt.SetParent(_panel, false);
            Column(rt.gameObject, new RectOffset(0, 0, 0, 0), 6, fit: false);
            return rt;
        }

        void Tab(Button b, bool selected)
        {
            b.targetGraphic.color = selected ? HudStyle.Accent : HudStyle.Button;
            var label = b.GetComponentInChildren<TextMeshProUGUI>();
            label.color = selected ? HudStyle.AccentText : HudStyle.Text;
        }

        // ---------- primitives (as HudBuilder's, at runtime) ----------

        RectTransform Glass(Transform parent, string name)
        {
            var img = Img(parent, name, HudStyle.Glass, _solid);
            img.raycastTarget = true;   // no painting through the panel
            var frame = Img(img.transform, "Frame", HudStyle.Chrome, _frame);
            Overlay(frame.rectTransform);
            foreach (var c in new[] { new Vector2(0, 1), new Vector2(1, 1), new Vector2(0, 0), new Vector2(1, 0) })
            {
                var br = Img(img.transform, "Bracket", HudStyle.ChromeBright, _bracket);
                br.type = Image.Type.Simple;
                var rt = br.rectTransform;
                rt.anchorMin = rt.anchorMax = c;
                rt.pivot = new Vector2(0.5f, 0.5f);
                rt.sizeDelta = new Vector2(12, 12);
                float sx = c.x == 0 ? 1 : -1, sy = c.y == 1 ? 1 : -1;
                rt.localScale = new Vector3(sx, sy, 1);
                rt.anchoredPosition = new Vector2(sx * 5f, -sy * 5f);
                Layout(br.gameObject).ignoreLayout = true;
            }
            return img.rectTransform;
        }

        Image Img(Transform parent, string name, Color color, Sprite sprite = null)
        {
            var go = new GameObject(name, typeof(RectTransform), typeof(Image));
            go.transform.SetParent(parent, false);
            var img = go.GetComponent<Image>();
            img.sprite = sprite ?? _solid;
            img.type = img.sprite != null && img.sprite.border != Vector4.zero ? Image.Type.Sliced : Image.Type.Simple;
            img.color = color;
            img.raycastTarget = false;
            return img;
        }

        Button MakeButton(Transform parent, string name, string text, float size, out TextMeshProUGUI label)
        {
            var img = Img(parent, name, HudStyle.Button);
            img.raycastTarget = true;
            var b = img.gameObject.AddComponent<Button>();
            var colors = b.colors;
            colors.normalColor = Color.white;
            colors.highlightedColor = new Color(1.7f, 1.7f, 1.7f);
            colors.pressedColor = new Color(0.8f, 0.8f, 0.8f);
            colors.selectedColor = Color.white;
            colors.disabledColor = new Color(1f, 1f, 1f, 0.35f);
            colors.fadeDuration = 0.08f;
            b.colors = colors;
            b.targetGraphic = img;
            var frame = Img(img.transform, "Frame", HudStyle.Chrome, _frame);
            Overlay(frame.rectTransform);
            label = Label(img.transform, "Label", text, size, HudStyle.Text, mono: true);
            label.fontStyle = FontStyles.UpperCase;
            label.alignment = TextAlignmentOptions.Center;
            label.characterSpacing = 1;
            var lr = label.rectTransform;
            lr.anchorMin = Vector2.zero;
            lr.anchorMax = Vector2.one;
            lr.offsetMin = new Vector2(8, 0);
            lr.offsetMax = new Vector2(-8, 0);
            img.gameObject.AddComponent<HudButtonFx>();
            return b;
        }

        TextMeshProUGUI Label(Transform parent, string name, string text, float size, Color color,
                              bool mono = false, bool bold = false, bool wrap = false,
                              TextAlignmentOptions align = TextAlignmentOptions.MidlineLeft)
        {
            var go = new GameObject(name, typeof(RectTransform), typeof(TextMeshProUGUI));
            go.transform.SetParent(parent, false);
            var t = go.GetComponent<TextMeshProUGUI>();
            t.font = mono ? _mono : _sans;
            t.text = text;
            t.fontSize = size;
            t.color = color;
            t.richText = true;
            t.fontStyle = bold ? FontStyles.Bold : FontStyles.Normal;
            t.textWrappingMode = wrap ? TextWrappingModes.Normal : TextWrappingModes.NoWrap;
            t.overflowMode = TextOverflowModes.Ellipsis;
            t.alignment = align;
            t.raycastTarget = false;
            return t;
        }

        void Section(Transform parent, string text)
        {
            var t = Label(parent, "Section", text, 10, HudStyle.ChromeBright, mono: true, bold: true);
            t.characterSpacing = 2;
            Fixed(t.gameObject, -1, 16);
        }

        void Divider(Transform parent) => Fixed(Img(parent, "Divider", HudStyle.Divider).gameObject, -1, 1);

        static RectTransform Row(Transform parent, string name, float height, float spacing)
        {
            var rt = new GameObject(name, typeof(RectTransform)).GetComponent<RectTransform>();
            rt.SetParent(parent, false);
            var h = rt.gameObject.AddComponent<HorizontalLayoutGroup>();
            h.spacing = spacing;
            h.childAlignment = TextAnchor.MiddleLeft;
            h.childControlWidth = h.childControlHeight = true;
            h.childForceExpandWidth = false;
            h.childForceExpandHeight = true;
            Fixed(rt.gameObject, -1, height);
            Layout(rt.gameObject).flexibleHeight = 0;
            return rt;
        }

        static void Column(GameObject go, RectOffset padding, float spacing, bool fit)
        {
            var v = go.AddComponent<VerticalLayoutGroup>();
            v.padding = padding;
            v.spacing = spacing;
            v.childControlWidth = v.childControlHeight = true;
            v.childForceExpandWidth = true;
            v.childForceExpandHeight = false;
            if (fit) go.AddComponent<ContentSizeFitter>().verticalFit = ContentSizeFitter.FitMode.PreferredSize;
        }

        static void Overlay(RectTransform rt)
        {
            rt.anchorMin = Vector2.zero;
            rt.anchorMax = Vector2.one;
            rt.offsetMin = rt.offsetMax = Vector2.zero;
            Layout(rt.gameObject).ignoreLayout = true;
        }

        static void Fixed(GameObject go, float width, float height)
        {
            var le = Layout(go);
            if (width >= 0) { le.preferredWidth = width; le.minWidth = width; }
            if (height >= 0) { le.preferredHeight = height; le.minHeight = height; }
        }

        static void Flex(GameObject go) => Layout(go).flexibleWidth = 1;

        static LayoutElement Layout(GameObject go)
        {
            var le = go.GetComponent<LayoutElement>();
            return le != null ? le : go.AddComponent<LayoutElement>();
        }
    }
}
