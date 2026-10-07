using UnityEngine;

namespace CoolCairo
{
    // The sun swings slowly across the afternoon sky, so building shading drifts like on a
    // real summer day. Purely visual: the temperatures are satellite medians, not time of day.
    public class SunCycle : MonoBehaviour
    {
        [SerializeField] float elevation = 55f;
        [SerializeField] float fromAzimuth = 110f, toAzimuth = 230f;
        [SerializeField] float secondsPerSwing = 90f;

        void Update()
        {
            float t = 0.5f - 0.5f * Mathf.Cos(Time.time * Mathf.PI / secondsPerSwing);   // ease back and forth
            float azimuth = Mathf.Lerp(fromAzimuth, toAzimuth, t);
            // Lower sun at the ends of the swing, highest in the middle.
            float height = elevation - 12f * Mathf.Abs(t - 0.5f) * 2f;
            transform.rotation = Quaternion.Euler(height, azimuth, 0f);
        }
    }
}
