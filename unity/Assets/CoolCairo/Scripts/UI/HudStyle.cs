using UnityEngine;

namespace CoolCairo
{
    // Shared by the editor-time HUD builder and the runtime DistrictUI controller: colours and
    // the names the controller looks elements up by. Rename an element here, not in one place.
    public static class HudStyle
    {
        // "Satellite mission control": dark glass panels outlined by thin cyan instrument lines,
        // monospaced readouts, Cairo orange only for what is selected.
        public static readonly Color Glass = Hex(0x050B14, 0.9f);        // Panel fill, map faintly shows through
        public static readonly Color GlassSolid = Hex(0x050B14, 0.96f);  // Popups and tooltip
        public static readonly Color Chrome = Hex(0x4FD6FF, 0.28f);      // Panel outlines
        public static readonly Color ChromeBright = Hex(0x4FD6FF, 0.95f); // Corner brackets, live marks
        public static readonly Color Text = Hex(0xE6F1FF);
        public static readonly Color Muted = Hex(0x7F93AD);
        public static readonly Color Accent = Hex(0xFF8A3D);      // Cairo orange, selected state
        public static readonly Color AccentText = Hex(0x1A0E05);  // Text on accent buttons
        public static readonly Color Good = Hex(0x4CD08A);        // Cooling / reduced exposure
        public static readonly Color Button = Hex(0x0B1626, 0.9f);
        public static readonly Color Track = Hex(0x1B2B40);
        public static readonly Color Divider = Hex(0x4FD6FF, 0.14f);

        // Element names (children of the HUD canvas).
        public const string TopBar = "TopBar";
        public const string Subtitle = "Subtitle";
        public const string Sidebar = "Sidebar";
        public const string Kpis = "Kpis";
        public const string Dock = "Dock";                     // Bottom tool dock
        public const string GlobeButton = "GlobeButton";
        public const string ViewButtonPrefix = "View_";        // + ViewMode name
        public const string ViewHint = "ViewHint";
        public const string ToolButtonPrefix = "Tool_";        // + Intervention name
        public const string ToolHint = "ToolHint";
        public const string BrushSlider = "BrushSlider";
        public const string BrushValue = "BrushValue";
        public const string ResetButton = "ResetButton";
        public const string ModelText = "ModelText";
        public const string ModelButton = "ModelButton";       // Shows / hides the model notes
        public const string ModelPanel = "ModelPanel";
        public const string KpiDelta = "Kpi_Delta";
        public const string KpiExposure = "Kpi_Exposure";
        public const string KpiResidents = "Kpi_Residents";
        public const string KpiValue = "Value";
        public const string KpiSub = "Sub";
        public const string KpiFlash = "Flash";                // Card glow when a result improves
        public const string Legend = "Legend";
        public const string LegendTitle = "LegendTitle";
        public const string LegendRamp = "LegendRamp";
        public const string LegendMin = "LegendMin";
        public const string LegendMax = "LegendMax";
        public const string LegendScale = "LegendScale";        // Ramp + labels group
        public const string LegendSwatches = "LegendSwatches";  // Materials view
        public const string LegendPalettes = "LegendPalettes";  // Heat view colour-scheme buttons
        public const string PaletteButtonPrefix = "Palette_";   // + HeatPalette name
        public const string Tooltip = "Tooltip";
        public const string TooltipTitle = "TooltipTitle";
        public const string TooltipBody = "TooltipBody";
        public const string Footer = "Footer";                  // The scrolling ticker text
        public const string Ticker = "Ticker";
        public const string ScanLine = "ScanLine";
        public const string LinkDot = "LinkDot";                // "SAT LINK ●"
        public const string Clock = "Clock";
        public const string FloatLabel = "FloatLabel";          // Template for "−0.6 °C" pop-ups
        public const string FiguresButton = "FiguresButton";    // Sidebar: opens the analysis maps
        public const string FigurePopup = "FigurePopup";
        public const string FigureCard = "FigureCard";
        public const string FigureTitle = "FigureTitle";
        public const string FigureCount = "FigureCount";
        public const string FigureImage = "FigureImage";
        public const string FigureCaption = "FigureCaption";
        public const string FigurePrev = "FigurePrev";
        public const string FigureNext = "FigureNext";
        public const string FigureClose = "FigureClose";

        static Color Hex(int rgb, float a = 1f) =>
            new Color(((rgb >> 16) & 255) / 255f, ((rgb >> 8) & 255) / 255f, (rgb & 255) / 255f, a);
    }
}
