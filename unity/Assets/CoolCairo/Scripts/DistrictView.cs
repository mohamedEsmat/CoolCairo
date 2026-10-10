using System;
using UnityEngine;

namespace CoolCairo
{
    public enum ViewMode { Materials, Heat, Risk, Growth }

    // Colour schemes for the Surface heat view, chosen with the buttons in the colour key.
    //   Report:  blue -> light grey -> orange, centred on the typical urban block (heatReferenceC),
    //            the same colours as the methodology report's maps.
    //   Inferno: black -> purple -> orange -> yellow, the classic thermal-camera look.
    //   Warm:    pale yellow -> orange -> dark red.
    public enum HeatPalette { Report, Inferno, Warm }

    // Loads district.json, builds the buildings mesh and the block-level ground overlay,
    // and recolours both whenever the view mode or interventions change.
    public class DistrictView : MonoBehaviour
    {
        [SerializeField] TextAsset districtJson;
        [SerializeField] Material buildingMaterial;  // CoolCairo/VertexColorLit
        [SerializeField] Material groundMaterial;    // URP Unlit, base map replaced at runtime

        [Header("Material colours")]
        [SerializeField] Color brightSurface = new Color(0.86f, 0.83f, 0.76f);
        [SerializeField] Color darkSurface = new Color(0.22f, 0.22f, 0.24f);
        [SerializeField] Color vegetation = new Color(0.33f, 0.55f, 0.27f);
        [SerializeField] Color soil = new Color(0.84f, 0.70f, 0.49f);
        // Treated surfaces get their own icy cyan / blue, used nowhere else on the map: plain
        // white and light grey were almost invisible next to Cairo's pale beige roofs.
        // Same colours as the treatment rings (TreatmentOverlay).
        [SerializeField] Color coolRoof = new Color(0.66f, 0.93f, 1f);       // #A8EEFF
        [SerializeField] Color coolPavement = new Color(0.25f, 0.62f, 0.85f); // #409ED9
        [SerializeField] Color wall = new Color(0.72f, 0.69f, 0.64f);
        [SerializeField] Color noData = new Color(0.5f, 0.5f, 0.5f);

        // Growth view (district.json blocks.growthClass). Orange and gold mark change, so they
        // stand out against quiet grey; open land is a darker khaki, distinct by lightness too.
        public static readonly Color GrowthNew = new Color(0.92f, 0.41f, 0.20f);     // #EB6834
        public static readonly Color GrowthDenser = new Color(0.95f, 0.76f, 0.31f);  // #F2C14E
        public static readonly Color GrowthStable = new Color(0.45f, 0.48f, 0.54f);  // #737A8A
        public static readonly Color GrowthOpen = new Color(0.63f, 0.56f, 0.42f);    // #A08F6C

        // Built in code, not serialized: a serialized Gradient is initialised by Unity to plain
        // white, which silently turned the whole heat view white.
        Gradient riskRamp;
        Gradient[] heatRamps;

        public DistrictData Data { get; private set; }
        public InterventionModel Model { get; private set; }
        public ViewMode Mode { get; private set; } = ViewMode.Heat;
        public HeatPalette Palette { get; private set; } = HeatPalette.Report;
        public float HeatMin { get; private set; }
        public float HeatMax { get; private set; }
        public float RiskMax { get; private set; }  // Person-degrees at the top of the risk scale.

        public event Action Loaded;

        BuildingMesh _buildings;
        Texture2D _groundTex;

        // Switching view or colour scheme cross-fades the old colours into the new ones;
        // painting updates instantly (it already changes gradually).
        public const float FadeSeconds = 0.4f;
        public bool Fading => _fade < 1f;
        float _fade = 1f;
        Color32[] _groundFrom, _groundTo, _groundShown, _buildFrom, _buildTo;

        void Awake()
        {
            heatRamps = new[] { ReportRamp(), InfernoRamp(), WarmRamp() };
            riskRamp = DefaultRiskRamp();
            Data = DistrictData.FromJson(districtJson.text);
            Model = new InterventionModel(Data);
            Model.Changed += Refresh;
            ComputeHeatRange();
            ComputeRiskRange();
            BuildGround();
            BuildBuildings();
            gameObject.AddComponent<TreeLayer>().Init(this, buildingMaterial);
            Refresh();
            Loaded?.Invoke();
        }

        public void SetMode(ViewMode mode)
        {
            if (mode != Mode) StartFade();
            Mode = mode;
            Refresh();
        }

        public void SetPalette(HeatPalette palette)
        {
            if (palette != Palette) StartFade();
            Palette = palette;
            Refresh();
        }

        // Fade from whatever is on screen now (even mid-fade) to the next Refresh's colours.
        void StartFade()
        {
            if (_groundShown == null) return;
            _groundFrom = (Color32[])_groundShown.Clone();
            _buildFrom = (Color32[])_buildings.Colors.Clone();
            _fade = 0f;
        }

        void Update()
        {
            if (!Fading) return;
            _fade = Mathf.Min(1f, _fade + Time.deltaTime / FadeSeconds);
            Show();
        }

        // Materials-view colours for the legend, in the order the legend shows them.
        public System.Collections.Generic.IEnumerable<(string label, Color color)> MaterialLegend()
        {
            yield return ("Vegetation", vegetation);
            yield return ("Dark surface: asphalt, dark roofs", darkSurface);
            yield return ("Pale surface: concrete, pale roofs", brightSurface);
            yield return ("Bare soil / sand", soil);
            yield return ("Cool roof, coated (your plan)", coolRoof);
            yield return ("Cool pavement, coated (your plan)", coolPavement);
        }

        // Growth-view colours for the legend, in the order the legend shows them.
        public System.Collections.Generic.IEnumerable<(string label, Color color)> GrowthLegend()
        {
            var g = Data.growth;
            int first = g?.firstYear ?? 2016, last = g?.lastYear ?? 2023;
            yield return ($"New built-up since {first}", GrowthNew);
            yield return ($"Denser since {first} (+{(g?.denserMin ?? 0.05f) * 100f:0} pts building cover)", GrowthDenser);
            yield return ($"Built up before {first}, little change", GrowthStable);
            yield return ($"Still open land in {last}", GrowthOpen);
        }

        public Color BlockGrowthColor(int block)
        {
            if (!Data.HasGrowth) return noData;
            return Data.blocks.growthClass[block] switch
            {
                3 => GrowthNew,
                2 => GrowthDenser,
                1 => GrowthStable,
                0 => GrowthOpen,
                _ => noData,
            };
        }

        public Color HeatColor(float lst)
        {
            var ramp = heatRamps[(int)Palette];
            if (Palette != HeatPalette.Report)
                return ramp.Evaluate(Mathf.InverseLerp(HeatMin, HeatMax, lst));
            // Report: the light-grey middle sits exactly on the typical urban block, so blue means
            // "cooler than typical" and orange "hotter" (the blocks that carry heat risk). The
            // wider side of the range sets the scale, so both sides use the same degrees per colour step.
            float reference = Data.model.heatReferenceC;
            float span = Mathf.Max(0.1f, Mathf.Max(reference - HeatMin, HeatMax - reference));
            return ramp.Evaluate(Mathf.Clamp01(0.5f + (lst - reference) / (2f * span)));
        }

        // Heat-risk view: zero-risk and unpopulated blocks get quiet, distinct greys so the
        // orange-to-purple hotspots stand out (a near-white zero washed the whole district out).
        public static readonly Color NoExcessHeat = new Color(0.42f, 0.48f, 0.58f);
        public static readonly Color NoResidents = new Color(0.27f, 0.29f, 0.34f);
        const float MinResidents = 1f;

        public Color RiskColor(float exposure) => riskRamp.Evaluate(Mathf.Clamp01(exposure / RiskMax));

        public Color BlockRiskColor(int block)
        {
            if (!Model.IsValid(block)) return noData;
            if (Model.Residents(block) < MinResidents) return NoResidents;
            float e = Model.Exposure(block);
            return e <= 0f ? NoExcessHeat : RiskColor(e);
        }

        void ComputeRiskRange()
        {
            var values = new System.Collections.Generic.List<float>();
            for (int i = 0; i < Data.BlockCount; i++)
            {
                float e = Model.Exposure(i, withInterventions: false);
                if (e > 0f) values.Add(e);
            }
            values.Sort();
            // Fixed to the baseline, so the colours visibly drop as interventions are painted.
            RiskMax = values.Count == 0 ? 1f : Mathf.Max(1f, values[(int)(0.98f * (values.Count - 1))]);
        }

        void ComputeHeatRange()
        {
            var values = new System.Collections.Generic.List<float>();
            for (int i = 0; i < Data.BlockCount; i++)
                if (Model.IsValid(i)) values.Add(Data.blocks.lstC[i]);
            values.Sort();
            if (values.Count == 0) { HeatMin = 30f; HeatMax = 50f; return; }
            // 2nd-98th percentile so a few outliers don't wash out the map.
            HeatMin = values[(int)(0.02f * (values.Count - 1))];
            HeatMax = values[(int)(0.98f * (values.Count - 1))];
        }

        void BuildGround()
        {
            _groundTex = new Texture2D(Data.cols, Data.rows, TextureFormat.RGBA32, false)
            {
                filterMode = FilterMode.Point, // Hard block edges: one pixel = one block, no fake detail.
                wrapMode = TextureWrapMode.Clamp,
            };
            var ground = GameObject.CreatePrimitive(PrimitiveType.Quad);
            ground.name = "Ground";
            ground.transform.SetParent(transform, false);
            float w = Data.cols * Data.blockSize, d = Data.rows * Data.blockSize;
            ground.transform.localPosition = new Vector3(w / 2f, 0f, d / 2f);
            ground.transform.localRotation = Quaternion.Euler(90f, 0f, 0f);
            ground.transform.localScale = new Vector3(w, d, 1f);
            var mat = new Material(groundMaterial);
            mat.mainTexture = _groundTex;
            ground.GetComponent<MeshRenderer>().sharedMaterial = mat;
            // Keep the MeshCollider: the brush raycasts against the ground.
        }

        void BuildBuildings()
        {
            _buildings = BuildingMeshBuilder.Build(Data.buildings);
            var go = new GameObject("Buildings", typeof(MeshFilter), typeof(MeshRenderer));
            go.transform.SetParent(transform, false);
            go.GetComponent<MeshFilter>().sharedMesh = _buildings.Mesh;
            go.GetComponent<MeshRenderer>().sharedMaterial = buildingMaterial;
        }

        void Refresh()
        {
            _groundTo ??= new Color32[Data.BlockCount];
            for (int i = 0; i < Data.BlockCount; i++) _groundTo[i] = GroundColor(i);

            var b = Data.buildings;
            var colors = _buildTo ??= new Color32[_buildings.Colors.Length];
            for (int i = 0; i < b.count; i++)
            {
                int block = b.blockIndex[i];
                Color roof, walls;
                if (Mode == ViewMode.Heat)
                {
                    roof = Model.IsValid(block) ? HeatColor(Model.Lst(block)) : noData;
                    walls = roof * 0.85f;
                }
                else if (Mode == ViewMode.Risk)
                {
                    roof = BlockRiskColor(block);
                    walls = roof * 0.85f;
                }
                else if (Mode == ViewMode.Growth)
                {
                    roof = BlockGrowthColor(block);
                    walls = roof * 0.85f;
                }
                else
                {
                    // Block-level statement: roofs in this block are X% dark. Not per-roof truth.
                    roof = Color.Lerp(brightSurface, darkSurface, Model.DarkRoofShareOfRoofs(block));
                    roof = Color.Lerp(roof, coolRoof, Model.Share(Intervention.CoolRoof, block));
                    walls = wall;
                }
                Fill(colors, _buildings.RoofStart[i], _buildings.RoofCount[i], roof);
                Fill(colors, _buildings.WallStart[i], _buildings.WallCount[i], walls);
            }
            Show();
        }

        // Upload the target colours, blended with the previous view's while a fade runs.
        void Show()
        {
            _groundShown ??= new Color32[Data.BlockCount];
            if (Fading)
            {
                float t = Mathf.SmoothStep(0f, 1f, _fade);
                for (int i = 0; i < _groundTo.Length; i++) _groundShown[i] = Color32.Lerp(_groundFrom[i], _groundTo[i], t);
                var shown = _buildings.Colors;
                for (int i = 0; i < _buildTo.Length; i++) shown[i] = Color32.Lerp(_buildFrom[i], _buildTo[i], t);
            }
            else
            {
                Array.Copy(_groundTo, _groundShown, _groundTo.Length);
                Array.Copy(_buildTo, _buildings.Colors, _buildTo.Length);
            }
            _groundTex.SetPixels32(_groundShown);
            _groundTex.Apply(false);
            _buildings.Mesh.SetColors(_buildings.Colors);
        }

        Color GroundColor(int i)
        {
            // Growth comes from building data, not temperature, so it ignores the LST mask.
            if (Mode == ViewMode.Growth) return BlockGrowthColor(i);
            if (!Model.IsValid(i)) return noData;
            if (Mode == ViewMode.Heat) return HeatColor(Model.Lst(i));
            if (Mode == ViewMode.Risk) return BlockRiskColor(i);

            var bl = Data.blocks;
            float ground = Mathf.Max(1e-4f, 1f - bl.roofFrac[i]);
            float planted = Model.TreePlantedFrac(i), coated = Model.PavementCoatedFrac(i);
            float greened = Model.ParkGreenedFrac(i);
            float veg = Mathf.Clamp01((bl.vegFrac[i] + planted + greened) / ground);
            float dark = Mathf.Clamp01((bl.darkGroundFrac[i] - planted - coated) / ground);
            float paved = Mathf.Clamp01(coated / ground);
            float sand = Mathf.Clamp01((bl.soilFrac[i] - greened) / ground);
            // Mix the ground shares; bright paved ground fills whatever share is left.
            float bright = Mathf.Max(0f, 1f - veg - dark - paved - sand);
            var c = brightSurface * bright + darkSurface * dark + coolPavement * paved + soil * sand + vegetation * veg;
            c.a = 1f;
            return c;
        }

        static void Fill(Color32[] colors, int start, int count, Color c)
        {
            Color32 c32 = c;
            for (int k = start; k < start + count; k++) colors[k] = c32;
        }

        static Gradient DefaultRiskRamp()
        {
            // Light peach (a little excess heat) -> orange -> deep purple (most person-degrees).
            // Zero risk is not on this ramp (see BlockRiskColor). Distinct from the temperature
            // ramp so the two views are never confused.
            var g = new Gradient();
            g.SetKeys(
                new[]
                {
                    new GradientColorKey(new Color(0.99f, 0.85f, 0.62f), 0f),
                    new GradientColorKey(new Color(0.98f, 0.60f, 0.26f), 0.35f),
                    new GradientColorKey(new Color(0.80f, 0.20f, 0.30f), 0.7f),
                    new GradientColorKey(new Color(0.33f, 0.07f, 0.40f), 1f),
                },
                new[] { new GradientAlphaKey(1f, 0f), new GradientAlphaKey(1f, 1f) });
            return g;
        }

        static Gradient Ramp(params (Color color, float at)[] keys)
        {
            var g = new Gradient();
            var colorKeys = new GradientColorKey[keys.Length];
            for (int k = 0; k < keys.Length; k++) colorKeys[k] = new GradientColorKey(keys[k].color, keys[k].at);
            g.SetKeys(colorKeys, new[] { new GradientAlphaKey(1f, 0f), new GradientAlphaKey(1f, 1f) });
            return g;
        }

        static Color Hex(int rgb) => new Color(((rgb >> 16) & 255) / 255f, ((rgb >> 8) & 255) / 255f, (rgb & 255) / 255f);

        // Same colours as the methodology report: diverging, neutral light grey in the middle.
        static Gradient ReportRamp() => Ramp((Hex(0x174A8B), 0f), (Hex(0x2A78D6), 0.25f), (Hex(0xF0EFEC), 0.5f),
                                             (Hex(0xEB6834), 0.75f), (Hex(0x9C3A14), 1f));

        // Matplotlib's "inferno", as in the Landsat maps of the analysis notebooks.
        static Gradient InfernoRamp() => Ramp((Hex(0x000004), 0f), (Hex(0x420A68), 0.2f), (Hex(0x932667), 0.45f),
                                              (Hex(0xDD513A), 0.7f), (Hex(0xFCA50A), 0.88f), (Hex(0xFCFFA4), 1f));

        // ColorBrewer "YlOrRd": warm only, pale yellow to dark red.
        static Gradient WarmRamp() => Ramp((Hex(0xFFFFB2), 0f), (Hex(0xFECC5C), 0.25f), (Hex(0xFD8D3C), 0.5f),
                                           (Hex(0xF03B20), 0.75f), (Hex(0xBD0026), 1f));
    }
}
