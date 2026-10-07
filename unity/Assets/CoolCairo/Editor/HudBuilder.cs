using System.Collections.Generic;
using System.IO;
using TMPro;
using UnityEditor;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.TextCore.LowLevel;
using UnityEngine.UI;

namespace CoolCairo.EditorTools
{
    // Builds the district HUD (uGUI Canvas) into the open scene. Called by ProjectSetup, so the
    // hierarchy is saved in Main.unity and can be restyled in the editor afterwards. Behaviour
    // lives in DistrictUI (and HudMotion for the animation), which find elements by the names
    // in HudStyle.
    //
    // Look: "satellite mission control". Dark glass panels with thin cyan outlines and corner
    // brackets, monospaced readouts (DejaVu Sans Mono), Liberation Sans only for longer text.
    public static class HudBuilder
    {
        const string SansPath = "Assets/TextMesh Pro/Resources/Fonts & Materials/LiberationSans SDF.asset";
        const string MonoTtf = "Assets/CoolCairo/Fonts/DejaVuSansMono.ttf";
        const string MonoAsset = "Assets/CoolCairo/Fonts/DejaVuSansMono SDF.asset";
        const string SpriteDir = "Assets/CoolCairo/UI";

        // Pre-baked into the font atlas; anything else is added on demand at runtime.
        const string MonoChars =
            " !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~" +
            "°→←−·●›‹×⌜⌝⌞⌟▲▼▸◂◆█Δ²±…–—©";

        static Sprite s_solid, s_frame, s_bracket, s_scan, s_dot;
        static TMP_FontAsset s_sans, s_mono;

        public static DistrictUI Build(DistrictView district, InterventionBrush brush, AnalysisFigure[] figures)
        {
            s_sans = AssetDatabase.LoadAssetAtPath<TMP_FontAsset>(SansPath);
            if (s_sans == null) throw new System.Exception("Run CoolCairo/Import TextMeshPro essentials first.");
            s_mono = EnsureMonoFont();
            EnsureSprites();

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

            BuildScreenFx(root);   // First, so every panel draws above the scan line.
            BuildTopBar(root);
            BuildSidebar(root);
            BuildKpis(root);
            BuildDock(root);
            BuildLegend(root);
            BuildTicker(root);
            BuildFloatLabel(root);
            BuildFigurePopup(root);
            BuildTooltip(root);    // Last, so it draws above everything.

            canvasGo.AddComponent<HudMotion>();
            var ui = canvasGo.AddComponent<DistrictUI>();
            var so = new SerializedObject(ui);
            so.FindProperty("district").objectReferenceValue = district;
            so.FindProperty("brush").objectReferenceValue = brush;
            var list = so.FindProperty("figures");
            list.arraySize = figures.Length;
            for (int i = 0; i < figures.Length; i++)
            {
                var item = list.GetArrayElementAtIndex(i);
                item.FindPropertyRelative("view").enumValueIndex = (int)figures[i].view;
                item.FindPropertyRelative("image").objectReferenceValue = figures[i].image;
                item.FindPropertyRelative("title").stringValue = figures[i].title;
                item.FindPropertyRelative("caption").stringValue = figures[i].caption;
            }
            so.ApplyModifiedPropertiesWithoutUndo();
            return ui;
        }

        // ---------- sections ----------

        // A slow scan line sweeping down the screen and brackets framing the map, like a sensor view.
        static void BuildScreenFx(Transform root)
        {
            var fx = new GameObject("ScreenFx", typeof(RectTransform)).GetComponent<RectTransform>();
            fx.SetParent(root, false);
            Stretch(fx, Vector2.zero, Vector2.one);
            fx.offsetMin = fx.offsetMax = Vector2.zero;

            var scan = Img(fx, HudStyle.ScanLine, s_scan, new Color(0.31f, 0.84f, 1f, 0.045f));
            scan.type = Image.Type.Simple;
            var srt = scan.rectTransform;
            srt.anchorMin = new Vector2(0, 1);
            srt.anchorMax = new Vector2(1, 1);
            srt.pivot = new Vector2(0.5f, 0.5f);
            srt.sizeDelta = new Vector2(0, 120);
            srt.anchoredPosition = Vector2.zero;

            Brackets(fx, 34, new Color(0.31f, 0.84f, 1f, 0.35f), inset: 8);
        }

        static void BuildTopBar(Transform root)
        {
            var bar = Glass(root, HudStyle.TopBar);
            var rt = bar.rectTransform;
            rt.anchorMin = new Vector2(0, 1);
            rt.anchorMax = new Vector2(1, 1);
            rt.pivot = new Vector2(0.5f, 1);
            rt.offsetMin = new Vector2(16, -16 - 56);
            rt.offsetMax = new Vector2(-16, -16);
            var h = bar.gameObject.AddComponent<HorizontalLayoutGroup>();
            h.padding = new RectOffset(20, 12, 8, 8);
            h.spacing = 16;
            h.childAlignment = TextAnchor.MiddleLeft;
            h.childControlWidth = h.childControlHeight = true;
            h.childForceExpandWidth = false;
            h.childForceExpandHeight = false;

            var title = Label(bar.transform, "Title", "[ COOLCAIRO <color=#4FD6FF>//</color> NASR CITY ]", 21, HudStyle.Text,
                              bold: true, mono: true);
            title.characterSpacing = 2;
            Fixed(title.gameObject, -1, 40);
            Fixed(Label(bar.transform, HudStyle.Subtitle, "", 12, HudStyle.Muted, mono: true).gameObject, -1, 40);
            Spacer(bar.transform);

            var dot = Img(bar.transform, HudStyle.LinkDot, s_dot, HudStyle.Good);
            dot.type = Image.Type.Simple;
            Fixed(dot.gameObject, 10, 10);
            Fixed(Label(bar.transform, "LinkLabel", "SAT LINK", 13, HudStyle.Good, bold: true, mono: true).gameObject, -1, 40);
            Fixed(Label(bar.transform, HudStyle.Clock, "UTC 00:00:00", 13, HudStyle.Muted, mono: true).gameObject, 120, 40);
            Fixed(Button(bar.transform, HudStyle.GlobeButton, "‹ GLOBE", 13).gameObject, 104, 36);
        }

        static void BuildSidebar(Transform root)
        {
            var side = Glass(root, HudStyle.Sidebar);
            var rt = side.rectTransform;
            rt.anchorMin = rt.anchorMax = rt.pivot = new Vector2(0, 1);
            rt.anchoredPosition = new Vector2(16, -16 - 56 - 14);
            rt.sizeDelta = new Vector2(330, 0);
            var v = VerticalFit(side.gameObject, new RectOffset(20, 20, 18, 18), 10);

            Section(side.transform, "01 // VIEW");
            // Two rows of two view buttons.
            var viewRows = new[] { Row(side.transform, "Views1", 38, 6), Row(side.transform, "Views2", 38, 6) };
            var viewNames = new[] { "Materials", "Surface heat", "Heat risk", "Growth" };
            var modes = new[] { ViewMode.Materials, ViewMode.Heat, ViewMode.Risk, ViewMode.Growth };
            for (int k = 0; k < modes.Length; k++)
                Flexible(Button(viewRows[k / 2], HudStyle.ViewButtonPrefix + modes[k], viewNames[k], 13).gameObject, width: 1);
            Label(side.transform, HudStyle.ViewHint, "", 13, HudStyle.Muted, wrap: true);
            Fixed(Button(side.transform, HudStyle.FiguresButton, "Analysis maps", 12).gameObject, -1, 34);

            Divider(side.transform);
            var model = Row(side.transform, "ModelRow", 24, 8);
            Flexible(Section(model, "02 // MODEL NOTES").gameObject, width: 1);
            Fixed(Button(model, HudStyle.ModelButton, "[+]", 12).gameObject, 44, 24);
            var panel = new GameObject(HudStyle.ModelPanel, typeof(RectTransform)).GetComponent<RectTransform>();
            panel.SetParent(side.transform, false);
            VerticalFit(panel.gameObject, new RectOffset(0, 0, 0, 0), 0, fit: false);
            Label(panel, HudStyle.ModelText, "", 12, HudStyle.Muted, wrap: true);
            panel.gameObject.SetActive(false);
        }

        static void BuildKpis(Transform root)
        {
            var box = new GameObject(HudStyle.Kpis, typeof(RectTransform)).GetComponent<RectTransform>();
            box.SetParent(root, false);
            box.anchorMin = box.anchorMax = box.pivot = new Vector2(1, 1);
            box.anchoredPosition = new Vector2(-16, -16 - 56 - 14);
            box.sizeDelta = new Vector2(3 * 244 + 2 * 12, 112);
            var h = box.gameObject.AddComponent<HorizontalLayoutGroup>();
            h.spacing = 12;
            h.childControlWidth = h.childControlHeight = true;
            h.childForceExpandWidth = h.childForceExpandHeight = true;
            Kpi(box, HudStyle.KpiDelta, "⌜ SURFACE TEMP · AVG ⌝");
            Kpi(box, HudStyle.KpiExposure, "⌜ HEAT EXPOSURE ⌝");
            Kpi(box, HudStyle.KpiResidents, "⌜ RESIDENTS COOLED ⌝");
        }

        static void Kpi(Transform parent, string name, string title)
        {
            var card = Glass(parent, name);
            Fixed(card.gameObject, 244, -1);   // equal widths, whatever the numbers
            // Glows green (or orange) for a moment when the result changes; DistrictUI drives it.
            var flash = Img(card.transform, HudStyle.KpiFlash, s_solid, new Color(HudStyle.Good.r, HudStyle.Good.g, HudStyle.Good.b, 0f));
            Overlay(flash.rectTransform);
            flash.transform.SetAsFirstSibling();
            var v = card.gameObject.AddComponent<VerticalLayoutGroup>();
            v.padding = new RectOffset(18, 18, 12, 12);
            v.spacing = 2;
            v.childControlWidth = v.childControlHeight = true;
            v.childForceExpandHeight = false;
            Label(card.transform, "Title", title, 11, HudStyle.ChromeBright, mono: true, height: 18).characterSpacing = 2;
            Label(card.transform, HudStyle.KpiValue, "", 30, HudStyle.Text, bold: true, mono: true, height: 42);
            Label(card.transform, HudStyle.KpiSub, "", 11, HudStyle.Muted, mono: true, height: 20);
        }

        // Bottom-centre tool dock: [ROOF] [TREE] [ROAD] [PARK], what the tool does, brush and reset.
        static void BuildDock(Transform root)
        {
            var dock = Glass(root, HudStyle.Dock);
            var rt = dock.rectTransform;
            rt.anchorMin = rt.anchorMax = rt.pivot = new Vector2(0.5f, 0);
            rt.anchoredPosition = new Vector2(0, 16 + 30 + 12);
            var h = dock.gameObject.AddComponent<HorizontalLayoutGroup>();
            h.padding = new RectOffset(18, 18, 14, 14);
            h.spacing = 18;
            h.childControlWidth = h.childControlHeight = true;
            h.childForceExpandWidth = false;
            h.childForceExpandHeight = true;   // so the divider rule spans the dock's height
            var fit = dock.gameObject.AddComponent<ContentSizeFitter>();
            fit.horizontalFit = fit.verticalFit = ContentSizeFitter.FitMode.PreferredSize;

            var tools = Column(dock.transform, "ToolColumn", 8, 4 * 112 + 3 * 8);
            var head = Row(tools, "ToolHeader", 18, 8);
            Section(head, "03 // INTERVENTION");
            Flexible(Label(head, "BrushHint", "L-DRAG PAINT · R-DRAG ERASE · ALT-DRAG ORBIT", 10, HudStyle.Muted,
                           mono: true, align: TextAlignmentOptions.Right).gameObject, width: 1);
            var row = Row(tools, "Tools", 58, 8);
            var keys = new[] { "ROOF", "TREE", "ROAD", "PARK" };
            var names = new[] { "cool roofs", "street trees", "cool pavement", "pocket parks" };
            var kinds = new[] { Intervention.CoolRoof, Intervention.Trees, Intervention.CoolPavement, Intervention.PocketPark };
            for (int k = 0; k < kinds.Length; k++)
            {
                var b = Button(row, HudStyle.ToolButtonPrefix + kinds[k], $"[{keys[k]}]\n<size=70%><alpha=#B0>{names[k]}</size>", 17);
                b.GetComponentInChildren<TextMeshProUGUI>().lineSpacing = -12;
                Fixed(b.gameObject, 112, 58);
            }
            var hint = Label(tools, HudStyle.ToolHint, "", 12, HudStyle.Muted, wrap: true);
            Fixed(hint.gameObject, -1, 34);

            var rule = Img(dock.transform, "Rule", s_solid, HudStyle.Divider);
            Fixed(rule.gameObject, 1, -1);

            var brush = Column(dock.transform, "BrushColumn", 8, 210);
            var brushRow = Row(brush, "BrushRow", 18, 6);
            Flexible(Section(brushRow, "BRUSH").gameObject, width: 1);
            Fixed(Label(brushRow, HudStyle.BrushValue, "", 12, HudStyle.Text, mono: true, align: TextAlignmentOptions.Right).gameObject, 120, 18);
            Slider(brush, HudStyle.BrushSlider, 0, 5);
            Fixed(Button(brush, HudStyle.ResetButton, "Reset all", 12).gameObject, -1, 36);
        }

        static void BuildLegend(Transform root)
        {
            var card = Glass(root, HudStyle.Legend);
            var rt = card.rectTransform;
            rt.anchorMin = rt.anchorMax = rt.pivot = new Vector2(1, 0);
            rt.anchoredPosition = new Vector2(-16, 16 + 30 + 12);
            rt.sizeDelta = new Vector2(360, 0);
            VerticalFit(card.gameObject, new RectOffset(16, 16, 14, 14), 8);

            // Wraps to as many lines as it needs (the old fixed height cut it off).
            Label(card.transform, HudStyle.LegendTitle, "", 12, HudStyle.Text, bold: true, wrap: true, mono: true);

            var scale = new GameObject(HudStyle.LegendScale, typeof(RectTransform)).GetComponent<RectTransform>();
            scale.SetParent(card.transform, false);
            VerticalFit(scale.gameObject, new RectOffset(0, 0, 0, 0), 4, fit: false);
            var ramp = new GameObject(HudStyle.LegendRamp, typeof(RectTransform), typeof(RawImage));
            ramp.transform.SetParent(scale, false);
            ramp.GetComponent<RawImage>().raycastTarget = false;
            Fixed(ramp, -1, 12);
            // Tick marks under the ramp, like an instrument scale.
            var ticks = new GameObject("Ticks", typeof(RectTransform)).GetComponent<RectTransform>();
            ticks.SetParent(scale, false);
            Fixed(ticks.gameObject, -1, 5);
            for (int k = 0; k <= 8; k++)
            {
                var tick = Img(ticks, "Tick", s_solid, k % 4 == 0 ? HudStyle.ChromeBright : HudStyle.Chrome);
                var trt = tick.rectTransform;
                trt.anchorMin = new Vector2(k / 8f, 0);
                trt.anchorMax = new Vector2(k / 8f, 1);
                trt.pivot = new Vector2(k / 8f, 0.5f);
                trt.sizeDelta = new Vector2(1, 0);
            }
            var labels = Row(scale, "Labels", 16, 0);
            Flexible(Label(labels, HudStyle.LegendMin, "", 12, HudStyle.Muted, mono: true).gameObject, width: 1);
            Flexible(Label(labels, HudStyle.LegendMax, "", 12, HudStyle.Muted, mono: true, align: TextAlignmentOptions.Right).gameObject, width: 1);

            var swatches = new GameObject(HudStyle.LegendSwatches, typeof(RectTransform)).GetComponent<RectTransform>();
            swatches.SetParent(card.transform, false);
            VerticalFit(swatches.gameObject, new RectOffset(0, 0, 0, 0), 4, fit: false);
            // Rows are filled in by DistrictUI from DistrictView's material colours.

            // Heat view only: three buttons to switch the colour scheme.
            var palettes = Row(card.transform, HudStyle.LegendPalettes, 26, 6);
            Fixed(Label(palettes, "PaletteLabel", "COLOURS", 10, HudStyle.Muted, mono: true).gameObject, 62, 26);
            var paletteNames = new[] { "Report", "Inferno", "Warm" };
            var paletteValues = new[] { HeatPalette.Report, HeatPalette.Inferno, HeatPalette.Warm };
            for (int k = 0; k < paletteValues.Length; k++)
                Flexible(Button(palettes, HudStyle.PaletteButtonPrefix + paletteValues[k], paletteNames[k], 11).gameObject, width: 1);
        }

        // Data sources and credits scroll past along the bottom, like a downlink feed.
        static void BuildTicker(Transform root)
        {
            var bar = Img(root, HudStyle.Ticker, s_solid, HudStyle.Glass);
            bar.raycastTarget = true;   // no painting through the ticker
            var rt = bar.rectTransform;
            rt.anchorMin = new Vector2(0, 0);
            rt.anchorMax = new Vector2(1, 0);
            rt.pivot = new Vector2(0.5f, 0);
            rt.offsetMin = new Vector2(16, 16);
            rt.offsetMax = new Vector2(-16, 16 + 30);
            var line = Img(bar.transform, "Line", s_solid, HudStyle.Chrome);
            line.rectTransform.anchorMin = new Vector2(0, 1);
            line.rectTransform.anchorMax = new Vector2(1, 1);
            line.rectTransform.pivot = new Vector2(0.5f, 1);
            line.rectTransform.sizeDelta = new Vector2(0, 1);

            var tag = Img(bar.transform, "Tag", s_solid, HudStyle.ChromeBright);
            tag.rectTransform.anchorMin = new Vector2(0, 0);
            tag.rectTransform.anchorMax = new Vector2(0, 1);
            tag.rectTransform.pivot = new Vector2(0, 0.5f);
            tag.rectTransform.sizeDelta = new Vector2(92, 0);
            var tagText = Label(tag.transform, "TagText", "DOWNLINK", 11, HudStyle.AccentText, bold: true, mono: true);
            Overlay(tagText.rectTransform);
            tagText.alignment = TextAlignmentOptions.Center;

            var viewport = new GameObject("Viewport", typeof(RectTransform), typeof(RectMask2D)).GetComponent<RectTransform>();
            viewport.SetParent(bar.transform, false);
            Stretch(viewport, Vector2.zero, Vector2.one, 92 + 12, 12);
            var text = Label(viewport, HudStyle.Footer, "", 12, HudStyle.Muted, mono: true);
            var trt = text.rectTransform;
            trt.anchorMin = new Vector2(0, 0);
            trt.anchorMax = new Vector2(0, 1);
            trt.pivot = new Vector2(0, 0.5f);
            trt.sizeDelta = new Vector2(4000, 0);
            text.overflowMode = TextOverflowModes.Overflow;
        }

        static void BuildFloatLabel(Transform root)
        {
            var t = Label(root, HudStyle.FloatLabel, "", 24, HudStyle.Good, bold: true, mono: true);
            var rt = t.rectTransform;
            rt.anchorMin = rt.anchorMax = Vector2.zero;
            rt.pivot = new Vector2(0.5f, 0f);
            rt.sizeDelta = new Vector2(200, 34);
            t.alignment = TextAlignmentOptions.Bottom;
            t.overflowMode = TextOverflowModes.Overflow;
            t.outlineWidth = 0.18f;
            t.outlineColor = new Color32(5, 11, 20, 255);
            t.gameObject.SetActive(false);
        }

        // A large card over a dimmed screen: title, the figure (aspect kept), caption, previous/next.
        // Hidden until the sidebar's "Analysis maps" button opens it; HudMotion slides it in.
        static void BuildFigurePopup(Transform root)
        {
            var overlay = Img(root, HudStyle.FigurePopup, null, new Color(0.01f, 0.02f, 0.04f, 0.78f));
            Overlay(overlay.rectTransform);
            overlay.raycastTarget = true;   // blocks clicks to the map behind
            overlay.gameObject.AddComponent<CanvasGroup>();

            var card = Glass(overlay.transform, HudStyle.FigureCard, solid: true);
            var rt = card.rectTransform;
            rt.anchorMin = rt.anchorMax = rt.pivot = new Vector2(0.5f, 0.5f);
            rt.sizeDelta = new Vector2(1320, 900);
            var v = card.gameObject.AddComponent<VerticalLayoutGroup>();
            v.padding = new RectOffset(26, 26, 18, 20);
            v.spacing = 12;
            v.childControlWidth = v.childControlHeight = true;
            v.childForceExpandWidth = true;
            v.childForceExpandHeight = false;

            var header = Row(card.transform, "FigureHeader", 34, 12);
            Fixed(Label(header, "FigureTag", "ANALYSIS MAP", 11, HudStyle.ChromeBright, mono: true).gameObject, 110, 34);
            Flexible(Label(header, HudStyle.FigureTitle, "", 19, HudStyle.Text, bold: true, mono: true).gameObject, width: 1);
            Fixed(Label(header, HudStyle.FigureCount, "", 13, HudStyle.Muted, mono: true, align: TextAlignmentOptions.Right).gameObject, 70, 34);
            Fixed(Button(header, HudStyle.FigureClose, "×", 20).gameObject, 44, 34);
            Divider(card.transform);

            // The figure keeps its own aspect ratio inside a frame that takes the remaining height.
            var frame = new GameObject("FigureFrame", typeof(RectTransform), typeof(LayoutElement));
            frame.transform.SetParent(card.transform, false);
            frame.GetComponent<LayoutElement>().flexibleHeight = 1;
            var image = new GameObject(HudStyle.FigureImage, typeof(RectTransform), typeof(RawImage), typeof(AspectRatioFitter));
            image.transform.SetParent(frame.transform, false);
            image.GetComponent<RawImage>().raycastTarget = false;
            var fit = image.GetComponent<AspectRatioFitter>();
            fit.aspectMode = AspectRatioFitter.AspectMode.FitInParent;
            fit.aspectRatio = 1.6f;

            Label(card.transform, HudStyle.FigureCaption, "", 14, HudStyle.Muted, wrap: true, height: 64);

            var nav = Row(card.transform, "FigureNav", 38, 10);
            Fixed(Button(nav, HudStyle.FigurePrev, "‹ Previous", 13).gameObject, 160, 38);
            Spacer(nav);
            Fixed(Label(nav, "FigureKeys", "← → TO PAGE · ESC TO CLOSE", 10, HudStyle.Muted, mono: true,
                        align: TextAlignmentOptions.Center).gameObject, 320, 38);
            Spacer(nav);
            Fixed(Button(nav, HudStyle.FigureNext, "Next ›", 13).gameObject, 160, 38);

            overlay.gameObject.SetActive(false);
        }

        static void BuildTooltip(Transform root)
        {
            var card = Glass(root, HudStyle.Tooltip, solid: true);
            card.raycastTarget = false;
            var rt = card.rectTransform;
            rt.anchorMin = rt.anchorMax = new Vector2(0, 0);
            rt.pivot = new Vector2(0, 1);
            rt.sizeDelta = new Vector2(330, 0);
            VerticalFit(card.gameObject, new RectOffset(14, 14, 10, 12), 4);
            Label(card.transform, HudStyle.TooltipTitle, "", 13, HudStyle.ChromeBright, bold: true, mono: true, height: 20);
            Label(card.transform, HudStyle.TooltipBody, "", 12, HudStyle.Muted, wrap: true);
            card.gameObject.SetActive(false);
        }

        // ---------- primitives ----------

        // A dark glass panel with a thin outline and bright corner brackets.
        static Image Glass(Transform parent, string name, bool solid = false)
        {
            var img = Img(parent, name, s_solid, solid ? HudStyle.GlassSolid : HudStyle.Glass);
            img.raycastTarget = true;
            var frame = Img(img.transform, "Frame", s_frame, HudStyle.Chrome);
            Overlay(frame.rectTransform);
            Brackets(img.rectTransform, 12, HudStyle.ChromeBright, inset: -1);
            return img;
        }

        static Image Img(Transform parent, string name, Sprite sprite, Color color)
        {
            var go = new GameObject(name, typeof(RectTransform), typeof(Image));
            go.transform.SetParent(parent, false);
            var img = go.GetComponent<Image>();
            img.sprite = sprite;
            img.type = sprite != null && sprite.border != Vector4.zero ? Image.Type.Sliced : Image.Type.Simple;
            img.color = color;
            img.raycastTarget = false;
            return img;
        }

        // Child that fills its parent and is ignored by the parent's layout group.
        static void Overlay(RectTransform rt)
        {
            rt.anchorMin = Vector2.zero;
            rt.anchorMax = Vector2.one;
            rt.offsetMin = rt.offsetMax = Vector2.zero;
            LayoutOf(rt.gameObject).ignoreLayout = true;
        }

        // Four L-shaped corner marks (one sprite, mirrored per corner).
        static void Brackets(RectTransform parent, float size, Color color, float inset)
        {
            var corners = new[] { new Vector2(0, 1), new Vector2(1, 1), new Vector2(0, 0), new Vector2(1, 0) };
            foreach (var c in corners)
            {
                var img = Img(parent, "Bracket", s_bracket, color);
                img.type = Image.Type.Simple;
                var rt = img.rectTransform;
                rt.anchorMin = rt.anchorMax = c;
                rt.pivot = new Vector2(0.5f, 0.5f);
                rt.sizeDelta = new Vector2(size, size);
                float sx = c.x == 0 ? 1 : -1, sy = c.y == 1 ? 1 : -1;
                rt.localScale = new Vector3(sx, sy, 1);
                rt.anchoredPosition = new Vector2(sx * (size / 2f + inset), -sy * (size / 2f + inset));
                LayoutOf(img.gameObject).ignoreLayout = true;
            }
        }

        static VerticalLayoutGroup VerticalFit(GameObject go, RectOffset padding, float spacing, bool fit = true)
        {
            var v = go.AddComponent<VerticalLayoutGroup>();
            v.padding = padding;
            v.spacing = spacing;
            v.childControlWidth = v.childControlHeight = true;
            v.childForceExpandWidth = true;
            v.childForceExpandHeight = false;
            if (fit) go.AddComponent<ContentSizeFitter>().verticalFit = ContentSizeFitter.FitMode.PreferredSize;
            return v;
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

        static RectTransform Column(Transform parent, string name, float spacing, float width)
        {
            var rt = new GameObject(name, typeof(RectTransform)).GetComponent<RectTransform>();
            rt.SetParent(parent, false);
            var v = rt.gameObject.AddComponent<VerticalLayoutGroup>();
            v.spacing = spacing;
            v.childControlWidth = v.childControlHeight = true;
            v.childForceExpandWidth = true;
            v.childForceExpandHeight = false;
            Fixed(rt.gameObject, width, -1);
            return rt;
        }

        static void Spacer(Transform parent)
        {
            var go = new GameObject("Spacer", typeof(RectTransform), typeof(LayoutElement));
            go.transform.SetParent(parent, false);
            go.GetComponent<LayoutElement>().flexibleWidth = 1;
        }

        static TextMeshProUGUI Label(Transform parent, string name, string text, float size, Color color,
                                     bool bold = false, bool wrap = false, float height = -1, bool mono = false,
                                     TextAlignmentOptions align = TextAlignmentOptions.Left)
        {
            var go = new GameObject(name, typeof(RectTransform), typeof(TextMeshProUGUI));
            go.transform.SetParent(parent, false);
            var t = go.GetComponent<TextMeshProUGUI>();
            t.font = mono ? s_mono : s_sans;
            t.text = text;
            t.fontSize = size;
            t.color = color;
            t.richText = true;
            t.fontStyle = bold ? FontStyles.Bold : FontStyles.Normal;
            t.textWrappingMode = wrap ? TextWrappingModes.Normal : TextWrappingModes.NoWrap;
            t.overflowMode = TextOverflowModes.Ellipsis;
            t.alignment = align == TextAlignmentOptions.Right ? TextAlignmentOptions.MidlineRight
                        : align == TextAlignmentOptions.Center ? TextAlignmentOptions.Center
                        : TextAlignmentOptions.MidlineLeft;
            t.raycastTarget = false;
            if (height > 0) Fixed(go, -1, height);
            return t;
        }

        static TextMeshProUGUI Section(Transform parent, string text)
        {
            var t = Label(parent, "Section_" + text, text, 11, HudStyle.ChromeBright, bold: true, mono: true, height: 18);
            t.characterSpacing = 4;
            return t;
        }

        static void Divider(Transform parent)
        {
            var img = Img(parent, "Divider", s_solid, HudStyle.Divider);
            Fixed(img.gameObject, -1, 1);
        }

        // Dark instrument button: fill (tinted by DistrictUI when selected), thin outline that
        // lights up on hover (HudButtonFx), monospaced upper-case label.
        static Button Button(Transform parent, string name, string text, float size)
        {
            var img = Img(parent, name, s_solid, HudStyle.Button);
            img.raycastTarget = true;
            var b = img.gameObject.AddComponent<Button>();
            var colors = b.colors;
            colors.normalColor = Color.white;
            colors.highlightedColor = new Color(1.7f, 1.7f, 1.7f);
            colors.pressedColor = new Color(0.8f, 0.8f, 0.8f);
            colors.selectedColor = Color.white;
            colors.disabledColor = new Color(1f, 1f, 1f, 0.35f);
            colors.colorMultiplier = 1f;
            colors.fadeDuration = 0.08f;
            b.colors = colors;
            b.targetGraphic = img;
            var frame = Img(img.transform, "Frame", s_frame, HudStyle.Chrome);
            Overlay(frame.rectTransform);
            var label = Label(img.transform, "Label", text, size, HudStyle.Text, mono: true);
            label.fontStyle = FontStyles.UpperCase;
            label.alignment = TextAlignmentOptions.Center;
            label.characterSpacing = 1;
            var lr = label.rectTransform;
            lr.anchorMin = Vector2.zero;
            lr.anchorMax = Vector2.one;
            lr.offsetMin = new Vector2(6, 0);
            lr.offsetMax = new Vector2(-6, 0);
            img.gameObject.AddComponent<HudButtonFx>();
            return b;
        }

        static Slider Slider(Transform parent, string name, float min, float max)
        {
            var root = new GameObject(name, typeof(RectTransform), typeof(Slider));
            root.transform.SetParent(parent, false);
            Fixed(root, -1, 22);

            var bg = Img(root.transform, "Background", s_solid, HudStyle.Track);
            Stretch(bg.rectTransform, new Vector2(0, 0.4f), new Vector2(1, 0.6f));

            var fillArea = new GameObject("Fill Area", typeof(RectTransform)).GetComponent<RectTransform>();
            fillArea.SetParent(root.transform, false);
            Stretch(fillArea, new Vector2(0, 0.4f), new Vector2(1, 0.6f), 0, 6);
            var fill = Img(fillArea, "Fill", s_solid, HudStyle.Accent);
            fill.rectTransform.sizeDelta = new Vector2(6, 0);

            var handleArea = new GameObject("Handle Slide Area", typeof(RectTransform)).GetComponent<RectTransform>();
            handleArea.SetParent(root.transform, false);
            Stretch(handleArea, Vector2.zero, Vector2.one, 3, 3);
            var hImg = Img(handleArea, "Handle", s_solid, HudStyle.ChromeBright);
            hImg.raycastTarget = true;
            hImg.rectTransform.sizeDelta = new Vector2(6, 0);

            var s = root.GetComponent<Slider>();
            s.fillRect = fill.rectTransform;
            s.handleRect = hImg.rectTransform;
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

        // ---------- assets: monospaced font and the few UI sprites ----------

        static TMP_FontAsset EnsureMonoFont()
        {
            var asset = AssetDatabase.LoadAssetAtPath<TMP_FontAsset>(MonoAsset);
            if (asset != null) return asset;
            var ttf = AssetDatabase.LoadAssetAtPath<Font>(MonoTtf) ?? throw new System.Exception($"Missing {MonoTtf}");
            asset = TMP_FontAsset.CreateFontAsset(ttf, 64, 6, GlyphRenderMode.SDFAA, 1024, 1024,
                                                  AtlasPopulationMode.Dynamic, true);
            asset.name = "DejaVuSansMono SDF";
            AssetDatabase.CreateAsset(asset, MonoAsset);
            asset.atlasTextures[0].name = "DejaVuSansMono SDF Atlas";
            AssetDatabase.AddObjectToAsset(asset.atlasTextures[0], asset);
            asset.material.name = "DejaVuSansMono SDF Material";
            AssetDatabase.AddObjectToAsset(asset.material, asset);
            asset.TryAddCharacters(MonoChars, out _);
            asset.fallbackFontAssetTable = new List<TMP_FontAsset> { s_sans };
            EditorUtility.SetDirty(asset);
            AssetDatabase.SaveAssets();
            return asset;
        }

        static void EnsureSprites()
        {
            s_solid = MakeSprite("Solid", 4, 4, (x, y) => 1f, border: 1);
            s_frame = MakeSprite("Frame", 16, 16, (x, y) => x == 0 || y == 0 || x == 15 || y == 15 ? 1f : 0f, border: 2);
            // L-shape in the top-left corner, 2 px thick.
            s_bracket = MakeSprite("Bracket", 16, 16, (x, y) => x < 2 || y >= 14 ? 1f : 0f, border: 0);
            // Soft horizontal band, brightest in the middle with a sharp leading edge.
            s_scan = MakeSprite("Scan", 4, 64, (x, y) => y < 32 ? Mathf.Pow(y / 32f, 2.2f) : (y < 34 ? 1f : 0f), border: 0);
            s_dot = MakeSprite("Dot", 32, 32, (x, y) =>
                Mathf.Clamp01(15.5f - Vector2.Distance(new Vector2(x + 0.5f, y + 0.5f), new Vector2(16, 16))), border: 0);
        }

        static Sprite MakeSprite(string name, int w, int h, System.Func<int, int, float> alpha, int border)
        {
            string path = $"{SpriteDir}/{name}.png";
            if (!File.Exists(path))
            {
                Directory.CreateDirectory(SpriteDir);
                var tex = new Texture2D(w, h, TextureFormat.RGBA32, false);
                for (int y = 0; y < h; y++)
                for (int x = 0; x < w; x++)
                    tex.SetPixel(x, y, new Color(1f, 1f, 1f, alpha(x, y)));
                File.WriteAllBytes(path, tex.EncodeToPNG());
                Object.DestroyImmediate(tex);
                AssetDatabase.ImportAsset(path);
            }
            var imp = (TextureImporter)AssetImporter.GetAtPath(path);
            imp.textureType = TextureImporterType.Sprite;
            imp.spriteImportMode = SpriteImportMode.Single;
            imp.spriteBorder = new Vector4(border, border, border, border);
            imp.mipmapEnabled = false;
            imp.filterMode = name == "Solid" || name == "Frame" ? FilterMode.Point : FilterMode.Bilinear;
            imp.textureCompression = TextureImporterCompression.Uncompressed;
            imp.alphaIsTransparency = true;
            imp.SaveAndReimport();
            return AssetDatabase.LoadAssetAtPath<Sprite>(path);
        }
    }
}
