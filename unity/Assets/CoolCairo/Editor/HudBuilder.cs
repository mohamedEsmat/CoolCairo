using TMPro;
using UnityEditor;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.UI;

namespace CoolCairo.EditorTools
{
    // Builds the district HUD (uGUI Canvas) into the open scene. Called by ProjectSetup, so the
    // hierarchy is saved in Main.unity and can be restyled in the editor afterwards. Behaviour
    // lives in DistrictUI, which finds elements by the names in HudStyle.
    public static class HudBuilder
    {
        const string FontPath = "Assets/TextMesh Pro/Resources/Fonts & Materials/LiberationSans SDF.asset";

        static Sprite s_rounded, s_knob;
        static TMP_FontAsset s_font;

        public static DistrictUI Build(DistrictView district, InterventionBrush brush)
        {
            s_rounded = AssetDatabase.GetBuiltinExtraResource<Sprite>("UI/Skin/UISprite.psd");
            s_knob = AssetDatabase.GetBuiltinExtraResource<Sprite>("UI/Skin/Knob.psd");
            s_font = AssetDatabase.LoadAssetAtPath<TMP_FontAsset>(FontPath);
            if (s_font == null) throw new System.Exception("Run CoolCairo/Import TextMeshPro essentials first.");

            var es = new GameObject("EventSystem", typeof(EventSystem), typeof(StandaloneInputModule));

            var canvasGo = new GameObject("HUD", typeof(RectTransform), typeof(Canvas), typeof(CanvasScaler),
                                          typeof(GraphicRaycaster));
            canvasGo.layer = LayerMask.NameToLayer("UI");
            var canvas = canvasGo.GetComponent<Canvas>();
            canvas.renderMode = RenderMode.ScreenSpaceOverlay;
            var scaler = canvasGo.GetComponent<CanvasScaler>();
            scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(1920, 1080);
            scaler.matchWidthOrHeight = 0.5f;
            var root = canvasGo.transform;

            BuildSidebar(root);
            BuildKpis(root);
            BuildLegend(root);
            BuildFooter(root);
            BuildTooltip(root); // Last, so it draws above everything.

            var ui = canvasGo.AddComponent<DistrictUI>();
            var so = new SerializedObject(ui);
            so.FindProperty("district").objectReferenceValue = district;
            so.FindProperty("brush").objectReferenceValue = brush;
            so.ApplyModifiedPropertiesWithoutUndo();
            return ui;
        }

        // ---------- sections ----------

        static void BuildSidebar(Transform root)
        {
            var side = Panel(root, HudStyle.Sidebar, HudStyle.Panel);
            var rt = side.rectTransform;
            rt.anchorMin = new Vector2(0, 0);
            rt.anchorMax = new Vector2(0, 1);
            rt.pivot = new Vector2(0, 0.5f);
            rt.offsetMin = new Vector2(16, 16);
            rt.offsetMax = new Vector2(16 + 340, -16);
            var v = side.gameObject.AddComponent<VerticalLayoutGroup>();
            v.padding = new RectOffset(22, 22, 22, 22);
            v.spacing = 10;
            v.childControlWidth = v.childControlHeight = true;
            v.childForceExpandWidth = true;
            v.childForceExpandHeight = false;

            // Header: title + back-to-globe.
            var header = Row(side.transform, "Header", 44, 8);
            var titles = new GameObject("Titles", typeof(RectTransform)).GetComponent<RectTransform>();
            titles.SetParent(header, false);
            var tv = titles.gameObject.AddComponent<VerticalLayoutGroup>();
            tv.childControlWidth = tv.childControlHeight = true;
            tv.childForceExpandHeight = false;
            Flexible(titles.gameObject, width: 1);
            Label(titles, "Title", "CoolCairo", 28, HudStyle.Text, bold: true, height: 32);
            Label(titles, "Subtitle", "Nasr City · Cairo", 14, HudStyle.Muted, height: 18);
            var globe = Button(header, HudStyle.GlobeButton, "‹ Globe", 13);
            Fixed(globe.gameObject, 86, 32);

            Divider(side.transform);
            Section(side.transform, "VIEW");
            var views = Row(side.transform, "Views", 40, 6);
            foreach (var mode in new[] { ViewMode.Materials, ViewMode.Heat, ViewMode.Risk })
            {
                string text = mode == ViewMode.Materials ? "Materials" : mode == ViewMode.Heat ? "Surface heat" : "Heat risk";
                Flexible(Button(views, HudStyle.ViewButtonPrefix + mode, text, 14).gameObject, width: 1);
            }
            Label(side.transform, HudStyle.ViewHint, "", 13, HudStyle.Muted, wrap: true, height: 54);

            Divider(side.transform);
            Section(side.transform, "INTERVENTION");
            var tools = Row(side.transform, "Tools", 44, 6);
            foreach (var tool in new[] { Intervention.CoolRoof, Intervention.Trees })
                Flexible(Button(tools, HudStyle.ToolButtonPrefix + tool,
                                tool == Intervention.CoolRoof ? "Cool roofs" : "Street trees", 15).gameObject, width: 1);
            Label(side.transform, HudStyle.ToolHint, "", 13, HudStyle.Muted, wrap: true, height: 54);

            var brushRow = Row(side.transform, "BrushRow", 20, 6);
            Flexible(Label(brushRow, "BrushLabel", "Brush size", 13, HudStyle.Text).gameObject, width: 1);
            Label(brushRow, HudStyle.BrushValue, "", 13, HudStyle.Text, align: TextAlignmentOptions.Right).gameObject
                .AddComponent<LayoutElement>().preferredWidth = 90;
            Slider(side.transform, HudStyle.BrushSlider, 0, 5);
            Label(side.transform, "BrushHint", "Left-drag to paint · Right-drag to erase · Alt-drag to orbit",
                  12, HudStyle.Muted, wrap: true, height: 32);
            var reset = Button(side.transform, HudStyle.ResetButton, "Reset interventions", 14);
            Fixed(reset.gameObject, -1, 38);

            // Push the model box to the bottom of the sidebar.
            var spacer = new GameObject("Spacer", typeof(RectTransform), typeof(LayoutElement));
            spacer.transform.SetParent(side.transform, false);
            spacer.GetComponent<LayoutElement>().flexibleHeight = 1;

            Divider(side.transform);
            Section(side.transform, "ABOUT THE MODEL");
            Label(side.transform, HudStyle.ModelText, "", 12, HudStyle.Muted, wrap: true, height: 110);
        }

        static void BuildKpis(Transform root)
        {
            var box = new GameObject("Kpis", typeof(RectTransform)).GetComponent<RectTransform>();
            box.SetParent(root, false);
            box.anchorMin = box.anchorMax = box.pivot = new Vector2(1, 1);
            box.anchoredPosition = new Vector2(-16, -16);
            box.sizeDelta = new Vector2(3 * 250 + 2 * 12, 118);
            var h = box.gameObject.AddComponent<HorizontalLayoutGroup>();
            h.spacing = 12;
            h.childControlWidth = h.childControlHeight = true;
            h.childForceExpandWidth = h.childForceExpandHeight = true;
            Kpi(box, HudStyle.KpiDelta, "AVERAGE BLOCK SURFACE TEMP.");
            Kpi(box, HudStyle.KpiExposure, "HEAT EXPOSURE");
            Kpi(box, HudStyle.KpiResidents, "RESIDENTS IN COOLED BLOCKS");
        }

        static void Kpi(Transform parent, string name, string title)
        {
            var card = Panel(parent, name, HudStyle.Card);
            var v = card.gameObject.AddComponent<VerticalLayoutGroup>();
            v.padding = new RectOffset(18, 18, 14, 14);
            v.spacing = 2;
            v.childControlWidth = v.childControlHeight = true;
            v.childForceExpandHeight = false;
            Label(card.transform, "Title", title, 12, HudStyle.Muted, height: 18);
            Label(card.transform, HudStyle.KpiValue, "", 32, HudStyle.Text, bold: true, height: 40);
            Label(card.transform, HudStyle.KpiSub, "", 13, HudStyle.Muted, height: 20);
        }

        static void BuildLegend(Transform root)
        {
            var card = Panel(root, HudStyle.Legend, HudStyle.Card);
            var rt = card.rectTransform;
            rt.anchorMin = rt.anchorMax = rt.pivot = new Vector2(1, 0);
            rt.anchoredPosition = new Vector2(-16, 52);
            rt.sizeDelta = new Vector2(330, 0);
            var v = card.gameObject.AddComponent<VerticalLayoutGroup>();
            v.padding = new RectOffset(16, 16, 12, 14);
            v.spacing = 8;
            v.childControlWidth = v.childControlHeight = true;
            v.childForceExpandHeight = false;
            var fit = card.gameObject.AddComponent<ContentSizeFitter>();
            fit.verticalFit = ContentSizeFitter.FitMode.PreferredSize;

            Label(card.transform, HudStyle.LegendTitle, "", 13, HudStyle.Text, bold: true, wrap: true, height: 18);

            var scale = new GameObject(HudStyle.LegendScale, typeof(RectTransform)).GetComponent<RectTransform>();
            scale.SetParent(card.transform, false);
            var sv = scale.gameObject.AddComponent<VerticalLayoutGroup>();
            sv.spacing = 4;
            sv.childControlWidth = sv.childControlHeight = true;
            sv.childForceExpandHeight = false;
            var ramp = new GameObject(HudStyle.LegendRamp, typeof(RectTransform), typeof(RawImage));
            ramp.transform.SetParent(scale, false);
            ramp.GetComponent<RawImage>().raycastTarget = false;
            Fixed(ramp, -1, 14);
            var labels = Row(scale, "Labels", 18, 0);
            Flexible(Label(labels, HudStyle.LegendMin, "", 12, HudStyle.Muted).gameObject, width: 1);
            Flexible(Label(labels, HudStyle.LegendMax, "", 12, HudStyle.Muted, align: TextAlignmentOptions.Right).gameObject, width: 1);

            var swatches = new GameObject(HudStyle.LegendSwatches, typeof(RectTransform)).GetComponent<RectTransform>();
            swatches.SetParent(card.transform, false);
            var gv = swatches.gameObject.AddComponent<VerticalLayoutGroup>();
            gv.spacing = 4;
            gv.childControlWidth = gv.childControlHeight = true;
            gv.childForceExpandHeight = false;
            // Rows are filled in by DistrictUI from DistrictView's material colours.
        }

        static void BuildFooter(Transform root)
        {
            var t = Label(root, HudStyle.Footer, "", 11, HudStyle.Muted, wrap: true);
            var rt = t.rectTransform;
            rt.anchorMin = new Vector2(0, 0);
            rt.anchorMax = new Vector2(1, 0);
            rt.pivot = new Vector2(0, 0);
            rt.offsetMin = new Vector2(16 + 340 + 16, 12);
            rt.offsetMax = new Vector2(-16 - 330 - 16, 44);
            t.alignment = TextAlignmentOptions.BottomLeft;
        }

        static void BuildTooltip(Transform root)
        {
            var card = Panel(root, HudStyle.Tooltip, new Color(0.05f, 0.08f, 0.13f, 0.96f));
            card.raycastTarget = false;
            var rt = card.rectTransform;
            rt.anchorMin = rt.anchorMax = new Vector2(0, 0);
            rt.pivot = new Vector2(0, 1);
            rt.sizeDelta = new Vector2(320, 0);
            var v = card.gameObject.AddComponent<VerticalLayoutGroup>();
            v.padding = new RectOffset(14, 14, 10, 12);
            v.spacing = 4;
            v.childControlWidth = v.childControlHeight = true;
            v.childForceExpandHeight = false;
            var fit = card.gameObject.AddComponent<ContentSizeFitter>();
            fit.verticalFit = ContentSizeFitter.FitMode.PreferredSize;
            Label(card.transform, HudStyle.TooltipTitle, "", 14, HudStyle.Text, bold: true, height: 20);
            Label(card.transform, HudStyle.TooltipBody, "", 12, HudStyle.Muted, wrap: true);
            card.gameObject.SetActive(false);
        }

        // ---------- primitives ----------

        static Image Panel(Transform parent, string name, Color color)
        {
            var go = new GameObject(name, typeof(RectTransform), typeof(Image));
            go.transform.SetParent(parent, false);
            var img = go.GetComponent<Image>();
            img.sprite = s_rounded;
            img.type = UnityEngine.UI.Image.Type.Sliced;
            img.color = color;
            return img;
        }

        static RectTransform Row(Transform parent, string name, float height, float spacing)
        {
            var rt = new GameObject(name, typeof(RectTransform)).GetComponent<RectTransform>();
            rt.SetParent(parent, false);
            var h = rt.gameObject.AddComponent<HorizontalLayoutGroup>();
            h.spacing = spacing;
            h.childControlWidth = h.childControlHeight = true;
            h.childForceExpandWidth = false;
            h.childForceExpandHeight = true;
            Fixed(rt.gameObject, -1, height);
            return rt;
        }

        static TextMeshProUGUI Label(Transform parent, string name, string text, float size, Color color,
                                     bool bold = false, bool wrap = false, float height = -1,
                                     TextAlignmentOptions align = TextAlignmentOptions.Left)
        {
            var go = new GameObject(name, typeof(RectTransform), typeof(TextMeshProUGUI));
            go.transform.SetParent(parent, false);
            var t = go.GetComponent<TextMeshProUGUI>();
            t.font = s_font;
            t.text = text;
            t.fontSize = size;
            t.color = color;
            t.fontStyle = bold ? FontStyles.Bold : FontStyles.Normal;
            t.textWrappingMode = wrap ? TextWrappingModes.Normal : TextWrappingModes.NoWrap;
            t.overflowMode = TextOverflowModes.Ellipsis;
            t.alignment = align == TextAlignmentOptions.Right ? TextAlignmentOptions.MidlineRight : TextAlignmentOptions.MidlineLeft;
            t.raycastTarget = false;
            if (height > 0) Fixed(go, -1, height);
            return t;
        }

        static void Section(Transform parent, string text) =>
            Label(parent, "Section_" + text, text, 11, HudStyle.Muted, bold: true, height: 16).characterSpacing = 6;

        static void Divider(Transform parent)
        {
            var go = new GameObject("Divider", typeof(RectTransform), typeof(Image));
            go.transform.SetParent(parent, false);
            var img = go.GetComponent<Image>();
            img.color = HudStyle.Divider;
            img.raycastTarget = false;
            Fixed(go, -1, 1);
        }

        static Button Button(Transform parent, string name, string text, float size)
        {
            var img = Panel(parent, name, HudStyle.Button);
            var b = img.gameObject.AddComponent<Button>();
            var colors = b.colors;
            colors.normalColor = Color.white;
            colors.highlightedColor = new Color(1.15f, 1.15f, 1.2f);
            colors.pressedColor = new Color(0.85f, 0.85f, 0.9f);
            colors.selectedColor = Color.white;
            colors.colorMultiplier = 1.2f;
            b.colors = colors;
            b.targetGraphic = img;
            var label = Label(img.transform, "Label", text, size, HudStyle.Text);
            label.alignment = TextAlignmentOptions.Center;
            var lr = label.rectTransform;
            lr.anchorMin = Vector2.zero;
            lr.anchorMax = Vector2.one;
            lr.offsetMin = new Vector2(6, 0);
            lr.offsetMax = new Vector2(-6, 0);
            return b;
        }

        static Slider Slider(Transform parent, string name, float min, float max)
        {
            var root = new GameObject(name, typeof(RectTransform), typeof(Slider));
            root.transform.SetParent(parent, false);
            Fixed(root, -1, 20);

            var bg = Panel(root.transform, "Background", HudStyle.Track);
            Stretch(bg.rectTransform, new Vector2(0, 0.35f), new Vector2(1, 0.65f));

            var fillArea = new GameObject("Fill Area", typeof(RectTransform)).GetComponent<RectTransform>();
            fillArea.SetParent(root.transform, false);
            Stretch(fillArea, new Vector2(0, 0.35f), new Vector2(1, 0.65f), 5, 10);
            var fill = Panel(fillArea, "Fill", HudStyle.Accent);
            fill.rectTransform.sizeDelta = new Vector2(10, 0);

            var handleArea = new GameObject("Handle Slide Area", typeof(RectTransform)).GetComponent<RectTransform>();
            handleArea.SetParent(root.transform, false);
            Stretch(handleArea, Vector2.zero, Vector2.one, 10, 10);
            var handle = new GameObject("Handle", typeof(RectTransform), typeof(Image));
            handle.transform.SetParent(handleArea, false);
            var hImg = handle.GetComponent<Image>();
            hImg.sprite = s_knob;
            hImg.color = HudStyle.Text;
            handle.GetComponent<RectTransform>().sizeDelta = new Vector2(20, 0);

            var s = root.GetComponent<Slider>();
            s.fillRect = fill.rectTransform;
            s.handleRect = handle.GetComponent<RectTransform>();
            s.targetGraphic = hImg;
            s.direction = UnityEngine.UI.Slider.Direction.LeftToRight;
            s.minValue = min;
            s.maxValue = max;
            s.wholeNumbers = true;
            return s;
        }

        static void Stretch(RectTransform rt, Vector2 min, Vector2 max, float left = 0, float right = 0)
        {
            rt.anchorMin = min;
            rt.anchorMax = max;
            rt.offsetMin = new Vector2(left, 0);
            rt.offsetMax = new Vector2(-right, 0);
        }

        static void Fixed(GameObject go, float width, float height)
        {
            var le = LayoutOf(go);
            if (width >= 0) { le.preferredWidth = width; le.minWidth = width; }
            if (height >= 0) { le.preferredHeight = height; le.minHeight = height; }
        }

        static void Flexible(GameObject go, float width)
        {
            LayoutOf(go).flexibleWidth = width;
        }

        // Explicit check: in the editor a missing component is a "fake null" that ?? misses.
        static LayoutElement LayoutOf(GameObject go)
        {
            var le = go.GetComponent<LayoutElement>();
            return le != null ? le : go.AddComponent<LayoutElement>();
        }
    }
}
