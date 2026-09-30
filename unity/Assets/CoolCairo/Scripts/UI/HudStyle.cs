using UnityEngine;

namespace CoolCairo
{
    // Shared by the editor-time HUD builder and the runtime DistrictUI controller: colours and
    // the names the controller looks elements up by. Rename an element here, not in one place.
    public static class HudStyle
    {
        // Dark "space" palette to match the starfield background.
        public static readonly Color Panel = Hex(0x0E1522, 0.94f);
        public static readonly Color Card = Hex(0x152033, 0.94f);
        public static readonly Color Divider = Hex(0x243248);
        public static readonly Color Text = Hex(0xE8EEF6);
        public static readonly Color Muted = Hex(0x8DA0B8);
        public static readonly Color Accent = Hex(0xFF8A3D);      // Cairo orange, selected state
        public static readonly Color AccentText = Hex(0x1A0E05);  // Text on accent buttons
        public static readonly Color Good = Hex(0x4CD08A);        // Cooling / reduced exposure
        public static readonly Color Button = Hex(0x1C2A40);
        public static readonly Color ButtonHover = Hex(0x26384F);
        public static readonly Color Track = Hex(0x2A3A52);

        // Element names (children of the HUD canvas).
        public const string Sidebar = "Sidebar";
        public const string GlobeButton = "GlobeButton";
        public const string ViewButtonPrefix = "View_";        // + ViewMode name
        public const string ViewHint = "ViewHint";
        public const string ToolButtonPrefix = "Tool_";        // + Intervention name
        public const string ToolHint = "ToolHint";
        public const string BrushSlider = "BrushSlider";
        public const string BrushValue = "BrushValue";
        public const string ResetButton = "ResetButton";
        public const string ModelText = "ModelText";
        public const string KpiDelta = "Kpi_Delta";
        public const string KpiExposure = "Kpi_Exposure";
        public const string KpiResidents = "Kpi_Residents";
        public const string KpiValue = "Value";
        public const string KpiSub = "Sub";
        public const string Legend = "Legend";
        public const string LegendTitle = "LegendTitle";
        public const string LegendRamp = "LegendRamp";
        public const string LegendMin = "LegendMin";
        public const string LegendMax = "LegendMax";
        public const string LegendScale = "LegendScale";        // Ramp + labels group
        public const string LegendSwatches = "LegendSwatches";  // Materials view
        public const string Tooltip = "Tooltip";
        public const string TooltipTitle = "TooltipTitle";
        public const string TooltipBody = "TooltipBody";
        public const string Footer = "Footer";

        static Color Hex(int rgb, float a = 1f) =>
            new Color(((rgb >> 16) & 255) / 255f, ((rgb >> 8) & 255) / 255f, (rgb & 255) / 255f, a);
    }
}
