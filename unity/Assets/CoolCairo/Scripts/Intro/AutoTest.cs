using System.Collections;
using System.Linq;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace CoolCairo
{
    // Soak test for crash hunting: run the app with `-autotest` and it drives itself through
    // loading -> globe -> fly into Cairo -> paint interventions -> back to globe, forever,
    // logging each step. Does nothing unless the flag is present.
    // `-screenshots <folder>` instead takes one tour, saves a PNG of each screen (for the report
    // and pitch) and quits.
    public class AutoTest : MonoBehaviour
    {
        static AutoTest s_instance;
        int _cycle;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Boot()
        {
            var args = System.Environment.GetCommandLineArgs();
            int shots = System.Array.IndexOf(args, "-screenshots");
            if (s_instance != null || (!args.Contains("-autotest") && shots < 0)) return;
            s_instance = new GameObject("AutoTest").AddComponent<AutoTest>();
            DontDestroyOnLoad(s_instance.gameObject);
            Application.logMessageReceived += (msg, trace, type) =>
            {
                if (type == LogType.Exception || type == LogType.Error) System.Console.Out.Flush();
            };
            if (shots >= 0 && shots + 1 < args.Length)
                s_instance.StartCoroutine(s_instance.ScreenshotTour(args[shots + 1]));
            else
                s_instance.StartCoroutine(s_instance.Loop());
        }

        IEnumerator ScreenshotTour(string folder)
        {
            System.IO.Directory.CreateDirectory(folder);
            yield return new WaitForSeconds(4.5f); // Loading screen, archive rows mid-sync.
            yield return Shot(folder, "01_loading");

            IntroController intro = null;
            while ((intro = FindFirstObjectByType<IntroController>()) == null || !intro.ReadyForInput) yield return null;
            yield return new WaitForSeconds(1f);
            yield return Shot(folder, "02_globe");

            intro.ChooseCity(0);
            yield return new WaitForSeconds(1.6f); // End of the fast approach, ~760 km up.
            yield return Shot(folder, "02b_approach");
            yield return new WaitForSeconds(2.8f); // End of the slow descent, before the fade.
            yield return Shot(folder, "03_flyin");

            DistrictView district = null;
            while ((district = FindFirstObjectByType<DistrictView>()) == null || district.Model == null) yield return null;
            yield return new WaitForSeconds(1.5f);
            district.SetMode(ViewMode.Heat);
            yield return Shot(folder, "04_heat_today");
            district.SetMode(ViewMode.Materials);
            yield return Shot(folder, "05_materials_today");
            district.SetMode(ViewMode.Risk);
            yield return Shot(folder, "06_risk_today");
            if (district.Data.HasGrowth)
            {
                district.SetMode(ViewMode.Growth);
                yield return Shot(folder, "06b_growth");
            }

            // A targeted plan: cool roofs + pocket parks on the riskiest third of populated blocks.
            var model = district.Model;
            var ranked = Enumerable.Range(0, district.Data.BlockCount)
                .Where(model.IsValid).OrderByDescending(b => model.Exposure(b, false)).ToList();
            foreach (int b in ranked.Take(ranked.Count / 3))
            {
                model.Apply(Intervention.CoolRoof, b, 1f);
                model.Apply(Intervention.PocketPark, b, 1f);
            }
            district.SetMode(ViewMode.Risk);   // (was still on Growth when there is growth data)
            yield return new WaitForSeconds(2f);   // let the result cards finish counting
            yield return Shot(folder, "07_risk_after_plan");
            district.SetMode(ViewMode.Heat);
            yield return Shot(folder, "08_heat_after_plan");
            Debug.Log($"[AutoTest] screenshots saved to {folder}");
            Application.Quit();
        }

        static IEnumerator Shot(string folder, string name)
        {
            yield return new WaitForSeconds(DistrictView.FadeSeconds + 0.3f);   // after the view cross-fade
            yield return new WaitForEndOfFrame();
            ScreenCapture.CaptureScreenshot(System.IO.Path.Combine(folder, name + ".png"));
            yield return null;
            yield return null;
        }

        IEnumerator Loop()
        {
            while (true)
            {
                _cycle++;
                Log("waiting for globe");
                IntroController intro = null;
                while ((intro = FindFirstObjectByType<IntroController>()) == null || !intro.ReadyForInput) yield return null;
                yield return new WaitForSeconds(1f);
                Log("choosing Cairo");
                intro.ChooseCity(0);

                DistrictView district = null;
                while ((district = FindFirstObjectByType<DistrictView>()) == null || district.Model == null) yield return null;
                Log("in district; painting");
                var model = district.Model;
                for (int i = 0; i < 400; i++)
                {
                    int block = Random.Range(0, district.Data.BlockCount);
                    var kind = (Intervention)(i % 4); // All four tools.
                    model.Apply(kind, block, Random.Range(-0.5f, 1f));
                    if (i % 50 == 0) district.SetMode((ViewMode)(i / 50 % 4)); // Materials, Heat, Risk, Growth.
                    yield return null;
                }
                Log($"painted; mean dT {model.MeanDelta():0.00}; exposure {model.TotalExposure(false):0} -> {model.TotalExposure():0}; back to globe");
                SceneManager.LoadScene(0);
                yield return null;
            }
        }

        void Log(string step) =>
            Debug.Log($"[AutoTest] cycle {_cycle} t={Time.realtimeSinceStartup:0.0}s mem={System.GC.GetTotalMemory(false) / (1024 * 1024)}MB: {step}");
    }

}
