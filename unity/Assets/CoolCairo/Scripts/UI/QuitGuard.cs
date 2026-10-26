using UnityEngine;

namespace CoolCairo
{
    // Exit with a second click: the first click arms it for a few seconds ("CONFIRM?"), so a stray
    // click during a live demo does not close the app. Shared by the globe screen and the district HUD.
    public static class QuitGuard
    {
        const float ArmSeconds = 3f;
        static float s_armedUntil = -1f;

        public static bool Armed => Time.unscaledTime < s_armedUntil;

        // Returns true when this click quits.
        public static bool Press()
        {
            if (Armed)
            {
                Quit();
                return true;
            }
            s_armedUntil = Time.unscaledTime + ArmSeconds;
            return false;
        }

        public static void Disarm() => s_armedUntil = -1f;

        static void Quit()
        {
#if UNITY_EDITOR
            UnityEditor.EditorApplication.isPlaying = false;
#else
            Application.Quit();
#endif
        }
    }
}
