using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace CoolCairo
{
    // Footage for the demo video: run the app with `-record <folder>` and it plays a scripted
    // tour (loading, globe and fly-in, the three views, painting a plan, the result, back to the
    // globe), saving every frame as a JPG under <folder>/<scene>/. Time.captureFramerate fixes
    // game time at 30 fps, so the footage is smooth however long each frame takes to save.
    // `-recordPlan A2=1.5,A3=13.6,...` sets scene lengths in seconds (the voice-over's); A2 is how
    // long the globe holds before the fly-in.
    public class DemoRecorder : MonoBehaviour
    {
        public const int Fps = 30;

        // While recording, the real mouse is ignored: no hover card or outline, no camera input.
        public static bool Recording { get; private set; }

        static DemoRecorder s_instance;
        string _folder, _scene;
        int _frame;
        readonly Dictionary<string, float> _plan = new Dictionary<string, float>
        {
            ["A1"] = 9f, ["A2"] = 1f, ["A3"] = 13f, ["A4"] = 12.5f, ["A5"] = 12.5f, ["A6"] = 4f,
        };

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Boot()
        {
            var args = System.Environment.GetCommandLineArgs();
            int i = System.Array.IndexOf(args, "-record");
            if (s_instance != null || i < 0 || i + 1 >= args.Length) return;
            s_instance = new GameObject("DemoRecorder").AddComponent<DemoRecorder>();
            DontDestroyOnLoad(s_instance.gameObject);
            s_instance._folder = args[i + 1];
            int p = System.Array.IndexOf(args, "-recordPlan");
            if (p >= 0 && p + 1 < args.Length)
                foreach (var part in args[p + 1].Split(','))
                {
                    var kv = part.Split('=');
                    if (kv.Length == 2 && float.TryParse(kv[1], System.Globalization.NumberStyles.Float,
                                                         System.Globalization.CultureInfo.InvariantCulture, out float sec))
                        s_instance._plan[kv[0].Trim()] = sec;
                }
            Recording = true;
            Time.captureFramerate = Fps;
            s_instance.StartCoroutine(s_instance.Capture());
            s_instance.StartCoroutine(s_instance.Tour());
        }

        // Saves the finished frame of the current scene, every frame.
        IEnumerator Capture()
        {
            while (true)
            {
                yield return new WaitForEndOfFrame();
                if (_scene == null) continue;
                var tex = ScreenCapture.CaptureScreenshotAsTexture();
                File.WriteAllBytes(Path.Combine(_folder, _scene, $"{_frame++:00000}.jpg"), tex.EncodeToJPG(92));
                Destroy(tex);
            }
        }

        void Begin(string scene)
        {
            Directory.CreateDirectory(Path.Combine(_folder, scene));
            _scene = scene;
            _frame = 0;
            Debug.Log($"[DemoRecorder] scene {scene}");
        }

        static IEnumerator Hold(float seconds)
        {
            for (int f = Mathf.RoundToInt(seconds * Fps); f > 0; f--) yield return null;
        }

        IEnumerator Tour()
        {
            // A1: the archive sync, until the list has held a moment after the last row.
            Begin("A1");
            IntroController intro = null;
            while ((intro = FindFirstObjectByType<IntroController>()) == null || !intro.LoadingDone) yield return null;
            yield return Hold(1.2f);

            // A2: the globe settles on the Middle East, then the fly-in into Nasr City.
            Begin("A2");
            while (!intro.ReadyForInput) yield return null;
            yield return Hold(_plan["A2"]);
            intro.ChooseCity(0);
            DistrictView district = null;
            while ((district = FindFirstObjectByType<DistrictView>()) == null || district.Model == null) yield return null;
            var brush = FindFirstObjectByType<InterventionBrush>();
            var model = district.Model;

            // A3: the three views, timed to the voice-over ("Materials", "Surface heat", "heat risk").
            float a3 = _plan["A3"];
            district.SetMode(ViewMode.Materials);
            Begin("A3");
            yield return Hold(a3 * 0.33f);
            district.SetMode(ViewMode.Heat);
            yield return Hold(a3 * 0.37f);
            district.SetMode(ViewMode.Risk);
            yield return Hold(a3 * 0.30f);

            // A4: paint the targeted plan block by block: cool roofs, then pocket parks, on the
            // riskiest third of populated blocks, ranked as in the report (ties by temperature).
            var ranked = Enumerable.Range(0, district.Data.BlockCount)
                .Where(model.IsValid).OrderByDescending(b => model.Exposure(b, false))
                .ThenByDescending(model.BaselineLst).ToList();
            var plan = ranked.Take(ranked.Count / 3).ToList();
            float a4 = _plan["A4"];
            Begin("A4");
            brush.Radius = 0;
            yield return Hold(0.8f);
            brush.Tool = Intervention.CoolRoof;
            yield return Paint(brush, plan, a4 * 0.45f);
            brush.Tool = Intervention.PocketPark;
            yield return Hold(0.4f);
            yield return Paint(brush, plan, a4 * 0.35f);
            yield return Hold(Mathf.Max(0f, a4 * 0.20f - 1.2f));

            // A5: the result cards settle, then the Materials view with the coated roofs and rings.
            float a5 = _plan["A5"];
            Begin("A5");
            yield return Hold(a5 * 0.45f);
            district.SetMode(ViewMode.Materials);
            yield return Hold(a5 * 0.55f);

            // A6: back to the globe and the cities that come next.
            Begin("A6");
            SceneManager.LoadScene(0);
            yield return Hold(_plan["A6"]);

            _scene = null;
            Debug.Log($"[DemoRecorder] footage saved to {_folder}");
            yield return null;
            Application.Quit();
        }

        // One dab per block, spread evenly over the given time, so the plan visibly grows.
        static IEnumerator Paint(InterventionBrush brush, List<int> blocks, float seconds)
        {
            int frames = Mathf.Max(1, Mathf.RoundToInt(seconds * Fps));
            float perFrame = blocks.Count / (float)frames, due = 0f;
            int next = 0;
            for (int f = 0; f < frames; f++)
            {
                due += perFrame;
                while (next < blocks.Count && next < Mathf.RoundToInt(due)) brush.PaintAround(blocks[next++], 1f);
                yield return null;
            }
            while (next < blocks.Count) brush.PaintAround(blocks[next++], 1f);
        }
    }
}
