using UnityEngine;

namespace CoolCairo
{
    // The app opens borderless fullscreen at the monitor's resolution, covering the taskbar.
    // Unity remembers the last window mode per PC, so the build setting alone would keep a
    // machine that once ran it windowed in a window: force it at every start. F11 toggles a
    // window. Runs with -screen-fullscreen on the command line (self-test, screenshot tour)
    // keep the mode they ask for.
    public class ScreenMode : MonoBehaviour
    {
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)]
        static void Init()
        {
            if (Application.isEditor) return;
            if (System.Array.IndexOf(System.Environment.GetCommandLineArgs(), "-screen-fullscreen") < 0) Fullscreen();
            var go = new GameObject("ScreenMode", typeof(ScreenMode));
            DontDestroyOnLoad(go);
        }

        static void Fullscreen()
        {
            var native = Screen.currentResolution;
            Screen.SetResolution(native.width, native.height, FullScreenMode.FullScreenWindow);
        }

        void Update()
        {
            if (!Input.GetKeyDown(KeyCode.F11)) return;
            if (Screen.fullScreenMode == FullScreenMode.Windowed) Fullscreen();
            else Screen.SetResolution(1600, 900, FullScreenMode.Windowed);
        }
    }
}
