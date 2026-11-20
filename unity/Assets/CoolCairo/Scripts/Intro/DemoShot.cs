using System;
using System.Collections;
using System.Linq;
using UnityEngine;

namespace CoolCairo
{
    // One screenshot of the app as the pitch shows it, for the slides:
    //   CoolCairo.exe -demoshot <file.png> -screen-fullscreen 0 -screen-width 1920 -screen-height 1080
    // Opens Nasr City, shows Heat risk, applies the report's targeted plan, opens the plan panel,
    // waits for the readouts to settle, saves the screen and quits. Does nothing without the flag.
    // With -demoview confidence: the Data confidence view instead, with the card of the most
    // populated low-confidence block pinned (no plan).
    public class DemoShot : MonoBehaviour
    {
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Boot()
        {
            var args = Environment.GetCommandLineArgs();
            int i = Array.IndexOf(args, "-demoshot");
            if (i < 0 || i + 1 >= args.Length) return;
            var go = new GameObject("DemoShot");
            DontDestroyOnLoad(go);
            var shot = go.AddComponent<DemoShot>();
            int v = Array.IndexOf(args, "-demoview");
            shot.StartCoroutine(shot.Run(args[i + 1], v >= 0 && v + 1 < args.Length ? args[v + 1] : ""));
        }

        IEnumerator Run(string path, string view)
        {
            IntroController intro = null;
            while ((intro = FindFirstObjectByType<IntroController>()) == null || !intro.ReadyForInput) yield return null;
            intro.ChooseCity(0);
            DistrictView district = null;
            while ((district = FindFirstObjectByType<DistrictView>()) == null || district.Model == null) yield return null;
            yield return new WaitForSeconds(1f);
            if (view == "confidence" && district.Data.HasQuality)
            {
                district.SetMode(ViewMode.Confidence);
                var b = district.Data.blocks;
                int block = Enumerable.Range(0, district.Data.BlockCount).Where(k => b.confidence[k] == 0)
                    .OrderByDescending(k => b.population[k]).FirstOrDefault();
                FindFirstObjectByType<DistrictUI>()?.PinBlock(block);
            }
            else
            {
                district.SetMode(ViewMode.Risk);
                district.Model.ApplyTargetedPlan();
                FindFirstObjectByType<PlanDashboard>()?.SetOpen(true);
            }
            yield return new WaitForSeconds(4f);   // readouts count up, the panel fades in
            ScreenCapture.CaptureScreenshot(path);
            yield return new WaitForSeconds(1.5f);
            Debug.Log($"[DemoShot] saved {path}");
            Application.Quit(0);
        }
    }
}
