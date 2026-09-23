using System.IO;
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
            ConfigurePlayer();
            AssetDatabase.SaveAssets();
            Debug.Log("CoolCairo setup complete.");
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
            cam.backgroundColor = new Color(0.93f, 0.92f, 0.89f);

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
            EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene(ScenePath, true) };
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
        }
    }
}
