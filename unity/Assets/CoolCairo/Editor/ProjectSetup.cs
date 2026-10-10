using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

namespace CoolCairo.EditorTools
{
    // One-click, repeatable project setup (also runnable headless:
    //   Unity -batchmode -quit -projectPath unity -executeMethod CoolCairo.EditorTools.ProjectSetup.Run).
    // Creates the URP asset, materials and Main scene, and imports export/district.json.
    public static class ProjectSetup
    {
        const string Root = "Assets/CoolCairo";
        const string DataAsset = Root + "/Data/district.json";
        const string ScenePath = Root + "/Main.unity";

        [MenuItem("CoolCairo/Import district.json from export")]
        public static void ImportDistrict()
        {
            string src = Path.GetFullPath(Path.Combine(Application.dataPath, "../../export/district.json"));
            if (!File.Exists(src))
            {
                Debug.LogError($"No export found at {src}. Run analysis/run_pipeline.py first.");
                return;
            }
            File.Copy(src, Path.GetFullPath(DataAsset), true);
            AssetDatabase.ImportAsset(DataAsset);
            Debug.Log($"Imported {src}");
        }

        [MenuItem("CoolCairo/Setup project and scene")]
        public static void Run()
        {
            ImportDistrict();
            var pipeline = EnsurePipeline();
            GraphicsSettings.defaultRenderPipeline = pipeline;
            for (int i = 0; i < QualitySettings.names.Length; i++)
            {
                QualitySettings.SetQualityLevel(i, false);
                QualitySettings.renderPipeline = null; // Inherit the default above.
            }

            var buildingMat = EnsureMaterial("Buildings", "CoolCairo/VertexColorLit");
            var groundMat = EnsureMaterial("Ground", "Universal Render Pipeline/Unlit");
            BuildScene(buildingMat, groundMat);
            BuildIntroScene();
            EditorBuildSettings.scenes = new[]
            {
                new EditorBuildSettingsScene(IntroScenePath, true), // Index 0: app entry.
                new EditorBuildSettingsScene(ScenePath, true),
            };
            ConfigurePlayer();
            AssetDatabase.SaveAssets();
            Debug.Log("CoolCairo setup complete.");
        }

        const string IntroScenePath = Root + "/Intro.unity";
        // Made by analysis/globe_textures.py from NASA Blue Marble Next Generation (July 2004).
        const string EarthTexture = Root + "/Globe/BlueMarble_2004-07_16384.jpg";
        const string MenaTexture = Root + "/Globe/BlueMarble_2004-07_MENA.jpg";

        static void BuildIntroScene()
        {
            // Keep full resolution (Unity would downscale to 2048 by default): the globe at Unity's
            // 16384 maximum (~2.4 km/px), the MENA patch at its native 5520 px (500 m/px).
            ImportFullSize(EarthTexture, 16384, TextureWrapMode.Repeat);
            ImportFullSize(MenaTexture, 8192, TextureWrapMode.Clamp);

            var earthMat = EnsureMaterial("Earth", "Universal Render Pipeline/Unlit");
            earthMat.SetTexture("_BaseMap", AssetDatabase.LoadAssetAtPath<Texture2D>(EarthTexture));
            var satMat = EnsureMaterial("Satellite", "Universal Render Pipeline/Unlit");
            satMat.SetColor("_BaseColor", new Color(0.45f, 0.9f, 1f));
            var markerMat = EnsureMaterial("Marker", "Universal Render Pipeline/Unlit");
            var flyInMat = EnsureMaterial("FlyIn", "CoolCairo/FadeTexture");
            var menaMat = EnsureMaterial("GlobePatch", "CoolCairo/FadeTexture");
            menaMat.SetTexture("_BaseMap", AssetDatabase.LoadAssetAtPath<Texture2D>(MenaTexture));
            menaMat.SetFloat("_Alpha", 1f);
            menaMat.SetFloat("_Edge", 0.05f);
            menaMat.renderQueue = 2999;  // Before the fly-in image (3000), which must draw on top.
            EditorUtility.SetDirty(menaMat);
            EditorUtility.SetDirty(earthMat);
            EditorUtility.SetDirty(satMat);

            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);

            var camGo = new GameObject("Main Camera", typeof(Camera), typeof(AudioListener));
            camGo.tag = "MainCamera";
            var cam = camGo.GetComponent<Camera>();
            cam.clearFlags = CameraClearFlags.SolidColor;
            cam.backgroundColor = SpaceColor;
            cam.nearClipPlane = 0.001f;
            cam.farClipPlane = 50f;
            var globeCam = camGo.AddComponent<GlobeCamera>();

            var earth = new GameObject("Earth", typeof(MeshFilter), typeof(MeshRenderer), typeof(Globe));
            earth.GetComponent<MeshRenderer>().sharedMaterial = earthMat;
            var mena = new GameObject("MENA patch", typeof(MeshFilter), typeof(MeshRenderer), typeof(GlobePatch));
            mena.GetComponent<MeshRenderer>().sharedMaterial = menaMat;

            var sats = new GameObject("Satellites").AddComponent<SatelliteOrbits>();

            var intro = new GameObject("Intro").AddComponent<IntroController>();
            Assign(intro, "districtJson", AssetDatabase.LoadAssetAtPath<TextAsset>(DataAsset));
            Assign(intro, "globeCamera", globeCam);
            Assign(intro, "satellites", sats);
            Assign(intro, "satelliteMaterial", satMat);
            Assign(intro, "markerMaterial", markerMat);
            Assign(intro, "flyInMaterial", flyInMat);
            AddStars(Vector3.zero, 40f);

            EditorSceneManager.SaveScene(scene, IntroScenePath);
        }

        static void ImportFullSize(string path, int maxSize, TextureWrapMode wrapU)
        {
            var importer = (TextureImporter)AssetImporter.GetAtPath(path);
            importer.maxTextureSize = maxSize;
            importer.wrapModeU = wrapU;
            importer.wrapModeV = TextureWrapMode.Clamp;
            importer.anisoLevel = 8;
            importer.textureCompression = TextureImporterCompression.Compressed;
            importer.SaveAndReimport();
        }

        static readonly Color SpaceColor = new Color(0.01f, 0.015f, 0.03f);

        static void AddStars(Vector3 centre, float radius)
        {
            var go = new GameObject("Stars", typeof(MeshFilter), typeof(MeshRenderer));
            go.transform.position = centre;
            var stars = go.AddComponent<StarField>();
            Assign(stars, "material", EnsureMaterial("Stars", "CoolCairo/VertexColorUnlit"));
            var so = new SerializedObject(stars);
            so.FindProperty("radius").floatValue = radius;
            so.ApplyModifiedPropertiesWithoutUndo();
        }

        // TextMeshPro essentials (fonts, shaders, settings) for the district UI. Non-interactive:
        // the menu item would open a blocking dialog in batch mode.
        [MenuItem("CoolCairo/Import TextMeshPro essentials")]
        public static void ImportTmpEssentials()
        {
            if (AssetDatabase.IsValidFolder("Assets/TextMesh Pro"))
            {
                Debug.Log("TextMeshPro essentials already present.");
                if (Application.isBatchMode) EditorApplication.Exit(0);
                return;
            }
            // Package import finishes asynchronously; in batch mode, run WITHOUT -quit and exit
            // from these callbacks once it is done.
            AssetDatabase.importPackageCompleted += name =>
            {
                Debug.Log($"Imported {name}.");
                if (Application.isBatchMode) EditorApplication.Exit(0);
            };
            AssetDatabase.importPackageFailed += (name, error) =>
            {
                Debug.LogError($"Import of {name} failed: {error}");
                if (Application.isBatchMode) EditorApplication.Exit(1);
            };
            TMPro.TMP_PackageResourceImporter.ImportResources(true, false, false);
        }

        [MenuItem("CoolCairo/Build Windows desktop app")]
        public static void BuildWindows()
        {
            bool dev = System.Environment.GetCommandLineArgs().Contains("-devbuild");
            var report = BuildPipeline.BuildPlayer(new BuildPlayerOptions
            {
                scenes = new[] { IntroScenePath, ScenePath },
                locationPathName = dev ? "Builds/WindowsDev/CoolCairo.exe" : "Builds/Windows/CoolCairo.exe",
                target = BuildTarget.StandaloneWindows64,
                // `-devbuild` on the command line: development player (on-screen errors, full logs).
                options = dev ? BuildOptions.Development : BuildOptions.None,
            });
            Debug.Log($"Build {report.summary.result}: {report.summary.totalSize / (1024 * 1024)} MB, " +
                      $"{report.summary.totalErrors} errors -> {report.summary.outputPath}");
            if (Application.isBatchMode && report.summary.result != UnityEditor.Build.Reporting.BuildResult.Succeeded)
                EditorApplication.Exit(1);
        }

        static UniversalRenderPipelineAsset EnsurePipeline()
        {
            const string path = Root + "/Rendering/URP.asset";
            var existing = AssetDatabase.LoadAssetAtPath<UniversalRenderPipelineAsset>(path);
            if (existing != null) return existing;
            Directory.CreateDirectory(Root + "/Rendering");
            var renderer = ScriptableObject.CreateInstance<UniversalRendererData>();
            AssetDatabase.CreateAsset(renderer, Root + "/Rendering/URP_Renderer.asset");
            var asset = UniversalRenderPipelineAsset.Create(renderer);
            asset.supportsHDR = false;         // Cheaper on WebGL, not needed for flat colours.
            asset.msaaSampleCount = 4;
            asset.shadowDistance = 0f;          // No real-time shadows yet; bake or enable later.
            AssetDatabase.CreateAsset(asset, path);
            return asset;
        }

        static Material EnsureMaterial(string name, string shaderName)
        {
            string path = $"{Root}/Rendering/{name}.mat";
            var mat = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (mat != null) return mat;
            var shader = Shader.Find(shaderName) ?? throw new System.Exception($"Shader not found: {shaderName}");
            mat = new Material(shader);
            AssetDatabase.CreateAsset(mat, path);
            return mat;
        }

        static void BuildScene(Material buildingMat, Material groundMat)
        {
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);

            var sun = new GameObject("Sun", typeof(Light));
            var light = sun.GetComponent<Light>();
            light.type = LightType.Directional;
            light.intensity = 1.2f;
            sun.transform.rotation = Quaternion.Euler(55f, 150f, 0f);
            sun.AddComponent<SunCycle>();   // slow swing across the sky, so shading drifts

            var camGo = new GameObject("Main Camera", typeof(Camera), typeof(AudioListener));
            camGo.tag = "MainCamera";
            var cam = camGo.GetComponent<Camera>();
            cam.farClipPlane = 20000f;
            cam.nearClipPlane = 1f;
            cam.clearFlags = CameraClearFlags.SolidColor;
            cam.backgroundColor = SpaceColor;

            // Stars around the district, centred on it and far enough to stay behind the
            // orbit camera's maximum distance (5 km).
            var data = DistrictData.FromJson(AssetDatabase.LoadAssetAtPath<TextAsset>(DataAsset).text);
            AddStars(new Vector3(data.cols * data.blockSize / 2f, 0f, data.rows * data.blockSize / 2f), 9000f);

            var districtGo = new GameObject("District");
            var view = districtGo.AddComponent<DistrictView>();
            Assign(view, "districtJson", AssetDatabase.LoadAssetAtPath<TextAsset>(DataAsset));
            Assign(view, "buildingMaterial", buildingMat);
            Assign(view, "groundMaterial", groundMat);

            var orbit = camGo.AddComponent<OrbitCamera>();
            Assign(orbit, "district", view);

            var tools = new GameObject("Tools");
            var brush = tools.AddComponent<InterventionBrush>();
            Assign(brush, "district", view);
            Assign(brush, "cam", cam);

            // Outlines of the hovered block and the brush footprint (URP Unlit, both faces).
            var highlightMat = EnsureMaterial("Highlight", "Universal Render Pipeline/Unlit");
            highlightMat.SetFloat("_Cull", 0f);
            EditorUtility.SetDirty(highlightMat);
            var highlight = tools.AddComponent<BlockHighlight>();
            Assign(highlight, "district", view);
            Assign(highlight, "brush", brush);
            Assign(highlight, "material", highlightMat);

            // Coloured rings around every painted block, one colour per measure, in all views.
            var ringMat = EnsureMaterial("Treatment", "CoolCairo/VertexColorUnlit");
            var rings = tools.AddComponent<TreatmentOverlay>();
            Assign(rings, "district", view);
            Assign(rings, "material", ringMat);
            var hud = HudBuilder.Build(view, brush, AnalysisFigures());

            // Living scene: hot air over the hottest blocks, and a green pulse plus a rising
            // "−0.6 °C" where the planner paints. Both draw with the transparent Glow shader.
            var glowMat = EnsureMaterial("Glow", "CoolCairo/Glow");
            var shimmer = districtGo.AddComponent<HeatShimmer>();
            Assign(shimmer, "district", view);
            Assign(shimmer, "material", glowMat);
            var feedback = tools.AddComponent<PaintFeedback>();
            Assign(feedback, "district", view);
            Assign(feedback, "brush", brush);
            Assign(feedback, "cam", cam);
            Assign(feedback, "material", glowMat);
            Assign(feedback, "labelTemplate", hud.transform.Find(HudStyle.FloatLabel));

            EditorSceneManager.SaveScene(scene, ScenePath);
        }

        // ---------- analysis maps ----------

        const string FiguresDir = Root + "/Figures";

        // Copy the analysis figures (docs/report/figures, made by analysis/report/build_report.py,
        // the same images as the methodology report) into the project.
        [MenuItem("CoolCairo/Import analysis maps from docs")]
        public static void ImportFigures()
        {
            string src = Path.GetFullPath(Path.Combine(Application.dataPath, "../../docs/report/figures"));
            if (!Directory.Exists(src))
            {
                Debug.LogError($"No figures at {src}. Run analysis/report/build_report.py first.");
                return;
            }
            Directory.CreateDirectory(Path.GetFullPath(FiguresDir));
            foreach (var file in Directory.GetFiles(src, "*.png"))
                File.Copy(file, Path.GetFullPath(Path.Combine(FiguresDir, Path.GetFileName(file))), true);
            AssetDatabase.Refresh();
            foreach (var file in Directory.GetFiles(src, "*.png"))
            {
                // Sharp, unscaled UI images: no mipmaps, no compression blur, full size up to 2048 px.
                var path = FiguresDir + "/" + Path.GetFileName(file);
                var importer = (TextureImporter)AssetImporter.GetAtPath(path);
                importer.textureType = TextureImporterType.Default;
                importer.mipmapEnabled = false;
                importer.wrapMode = TextureWrapMode.Clamp;
                importer.maxTextureSize = 2048;
                importer.textureCompression = TextureImporterCompression.Uncompressed;
                importer.SaveAndReimport();
            }
            Debug.Log($"Imported analysis maps from {src}");
        }

        // Which figure belongs to which view, with the text shown under it.
        static AnalysisFigure[] AnalysisFigures()
        {
            ImportFigures();
            AnalysisFigure F(ViewMode view, string file, string title, string caption) => new AnalysisFigure
            {
                view = view,
                image = AssetDatabase.LoadAssetAtPath<Texture2D>(FiguresDir + "/" + file),
                title = title,
                caption = caption,
            };
            const string district = "Nasr City from the analysis: (a) Sentinel-2 summer photo, (b) surface materials " +
                                    "at 10 m, (c) summer surface temperature per 90 m block, (d) heat risk: residents × °C " +
                                    "above the typical block. White blocks in (d) are cooler than typical.";
            var all = new[]
            {
                F(ViewMode.Materials, "fig2_district.png", "Nasr City: photo, materials, heat and risk", district),
                F(ViewMode.Heat, "fig1_study_area.png", "East Cairo: summer surface temperature",
                  "The model area. (a) Sentinel-2 summer photo; (b) Landsat summer surface temperature per 90 m block, " +
                  "centred on the typical urban block. Bare desert (orange) is hotter than the built, irrigated city " +
                  "(blue). The box is the Nasr City district shown in this app."),
                F(ViewMode.Heat, "fig3_model_fit.png", "Heat model: tested on areas it never saw",
                  "Measured vs predicted block temperature, with whole 1 km areas hidden while the model learned " +
                  "(spatial cross-validation). Good enough to compare cooling measures, not to predict one block exactly."),
                F(ViewMode.Heat, "fig4_hyperspectral.png", "Does hyperspectral data help?",
                  "How well each set of satellite bands explains block surface temperature, tested on hidden 1, 2 and 3 km " +
                  "areas. EnMAP's full spectrum clearly beats Sentinel-2. Contains modified EnMAP data © DLR [2025]."),
                F(ViewMode.Risk, "fig2_district.png", "Nasr City: photo, materials, heat and risk", district),
                F(ViewMode.Risk, "fig5_interventions.png", "What each cooling measure would do",
                  "Change in Nasr City's heat exposure. Blue: each measure at full adoption in every block. Orange: cool " +
                  "roofs and pocket parks on only the riskiest third of blocks."),
                F(ViewMode.Growth, "fig6_growth.png", "Urban growth 2016–2023",
                  "From Google Open Buildings Temporal: (a) block classes, same colours as this view; (b) building " +
                  "footprint area per year; (c) mean summer surface temperature of blocks built before 2016, built " +
                  "2016–2023 and still open."),
            };
            var found = all.Where(f => f.image != null).ToArray();
            if (found.Length < all.Length) Debug.LogWarning("Some analysis maps are missing; rebuild the report figures.");
            return found;
        }

        static void Assign(Object target, string field, Object value)
        {
            var so = new SerializedObject(target);
            so.FindProperty(field).objectReferenceValue = value;
            so.ApplyModifiedPropertiesWithoutUndo();
        }

        static void ConfigurePlayer()
        {
            PlayerSettings.productName = "CoolCairo";
            PlayerSettings.companyName = "CoolCairo";
            PlayerSettings.colorSpace = ColorSpace.Linear;
            PlayerSettings.WebGL.compressionFormat = WebGLCompressionFormat.Brotli;
            // Lets the build run on hosts that cannot set Content-Encoding headers (e.g. GitHub Pages).
            PlayerSettings.WebGL.decompressionFallback = true;
            PlayerSettings.WebGL.dataCaching = true;
            PlayerSettings.stripEngineCode = true;
            // Desktop app (primary target): borderless fullscreen at the monitor's resolution
            // (ScreenMode forces it at start); F11 switches to a resizable 1600x900 window.
            PlayerSettings.fullScreenMode = FullScreenMode.FullScreenWindow;
            PlayerSettings.defaultIsNativeResolution = true;
            PlayerSettings.defaultScreenWidth = 1600;
            PlayerSettings.defaultScreenHeight = 900;
            PlayerSettings.resizableWindow = true;
            PlayerSettings.runInBackground = true;
        }
    }
}
