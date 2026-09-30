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
        const string EarthTexture = Root + "/Globe/BlueMarble_2004-07_5400.jpg";

        static void BuildIntroScene()
        {
            // Keep the full 5400 px NASA Blue Marble (Unity would downscale to 2048 by default).
            var importer = (TextureImporter)AssetImporter.GetAtPath(EarthTexture);
            importer.maxTextureSize = 8192;
            importer.wrapModeU = TextureWrapMode.Repeat;
            importer.wrapModeV = TextureWrapMode.Clamp;
            importer.anisoLevel = 4;
            importer.SaveAndReimport();

            var earthMat = EnsureMaterial("Earth", "Universal Render Pipeline/Unlit");
            earthMat.SetTexture("_BaseMap", AssetDatabase.LoadAssetAtPath<Texture2D>(EarthTexture));
            var satMat = EnsureMaterial("Satellite", "Universal Render Pipeline/Unlit");
            satMat.SetColor("_BaseColor", new Color(0.45f, 0.9f, 1f));
            var markerMat = EnsureMaterial("Marker", "Universal Render Pipeline/Unlit");
            var flyInMat = EnsureMaterial("FlyIn", "CoolCairo/FadeTexture");
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
            var hud = tools.AddComponent<HUD>();
            Assign(hud, "district", view);
            Assign(hud, "brush", brush);

            EditorSceneManager.SaveScene(scene, ScenePath);
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
            // Desktop app (primary target): windowed 1600x900, resizable.
            PlayerSettings.fullScreenMode = FullScreenMode.Windowed;
            PlayerSettings.defaultScreenWidth = 1600;
            PlayerSettings.defaultScreenHeight = 900;
            PlayerSettings.resizableWindow = true;
            PlayerSettings.runInBackground = true;
        }
    }
}
