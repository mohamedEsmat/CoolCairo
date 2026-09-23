using System;
using UnityEngine;

namespace CoolCairo
{
    public enum ViewMode { Materials, Heat }

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
        [SerializeField] Color coolRoof = new Color(0.97f, 0.98f, 1f);
        [SerializeField] Color wall = new Color(0.72f, 0.69f, 0.64f);
        [SerializeField] Color noData = new Color(0.5f, 0.5f, 0.5f);

        [Header("Heat scale")]
        [SerializeField] Gradient heatRamp;

        public DistrictData Data { get; private set; }
        public InterventionModel Model { get; private set; }
        public ViewMode Mode { get; private set; } = ViewMode.Heat;
        public float HeatMin { get; private set; }
        public float HeatMax { get; private set; }

        public event Action Loaded;

        BuildingMesh _buildings;
        Texture2D _groundTex;

        void Awake()
        {
            if (heatRamp == null || heatRamp.colorKeys.Length < 2) heatRamp = DefaultHeatRamp();
            Data = DistrictData.FromJson(districtJson.text);
            Model = new InterventionModel(Data);
            Model.Changed += Refresh;
            ComputeHeatRange();
            BuildGround();
            BuildBuildings();
            Refresh();
            Loaded?.Invoke();
        }

        public void SetMode(ViewMode mode)
        {
            Mode = mode;
            Refresh();
        }

        public Color HeatColor(float lst) => heatRamp.Evaluate(Mathf.InverseLerp(HeatMin, HeatMax, lst));

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
            var pixels = new Color32[Data.BlockCount];
            for (int i = 0; i < Data.BlockCount; i++) pixels[i] = GroundColor(i);
            _groundTex.SetPixels32(pixels);
            _groundTex.Apply(false);

            var b = Data.buildings;
            var colors = _buildings.Colors;
            for (int i = 0; i < b.count; i++)
            {
                int block = b.blockIndex[i];
                Color roof, walls;
                if (Mode == ViewMode.Heat)
                {
                    roof = Model.IsValid(block) ? HeatColor(Model.Lst(block)) : noData;
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
            _buildings.Mesh.SetColors(colors);
        }

        Color GroundColor(int i)
        {
            if (!Model.IsValid(i)) return noData;
            if (Mode == ViewMode.Heat) return HeatColor(Model.Lst(i));

            var bl = Data.blocks;
            float ground = Mathf.Max(1e-4f, 1f - bl.roofFrac[i]);
            float plantedFromDark = Model.Share(Intervention.Trees, i)
                                    * InterventionModel.MaxTreeShareOfDarkGround * bl.darkGroundFrac[i];
            float veg = Mathf.Clamp01((bl.vegFrac[i] + plantedFromDark) / ground);
            float dark = Mathf.Clamp01((bl.darkGroundFrac[i] - plantedFromDark) / ground);
            float sand = Mathf.Clamp01(bl.soilFrac[i] / ground);
            // Mix the ground shares; bright paved ground fills whatever share is left.
            float bright = Mathf.Max(0f, 1f - veg - dark - sand);
            var c = brightSurface * bright + darkSurface * dark + soil * sand + vegetation * veg;
            c.a = 1f;
            return c;
        }

        static void Fill(Color32[] colors, int start, int count, Color c)
        {
            Color32 c32 = c;
            for (int k = start; k < start + count; k++) colors[k] = c32;
        }

        static Gradient DefaultHeatRamp()
        {
            // Cool blue -> pale yellow -> deep red. Sequential, readable for common colour-vision deficiencies.
            var g = new Gradient();
            g.SetKeys(
                new[]
                {
                    new GradientColorKey(new Color(0.19f, 0.33f, 0.62f), 0f),
                    new GradientColorKey(new Color(0.99f, 0.93f, 0.65f), 0.5f),
                    new GradientColorKey(new Color(0.65f, 0.06f, 0.09f), 1f),
                },
                new[] { new GradientAlphaKey(1f, 0f), new GradientAlphaKey(1f, 1f) });
            return g;
        }
    }
}
