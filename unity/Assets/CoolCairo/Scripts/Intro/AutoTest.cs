using System.Collections;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace CoolCairo
{
    // Soak test for crash hunting: run the app with `-autotest` and it drives itself through
    // loading -> globe -> fly into Cairo -> paint interventions -> back to globe, forever,
    // logging each step. Does nothing unless the flag is present.
    public class AutoTest : MonoBehaviour
    {
        static AutoTest s_instance;
        int _cycle;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        static void Boot()
        {
            if (s_instance != null || !System.Environment.GetCommandLineArgs().Contains("-autotest")) return;
            s_instance = new GameObject("AutoTest").AddComponent<AutoTest>();
            DontDestroyOnLoad(s_instance.gameObject);
            Application.logMessageReceived += (msg, trace, type) =>
            {
                if (type == LogType.Exception || type == LogType.Error) System.Console.Out.Flush();
            };
            s_instance.StartCoroutine(s_instance.Loop());
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
                    if (i % 50 == 0) district.SetMode((ViewMode)(i / 50 % 3)); // Materials, Heat, Risk.
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

    static class ArgsExtensions
    {
        public static bool Contains(this string[] args, string flag) => System.Array.IndexOf(args, flag) >= 0;
    }
}
