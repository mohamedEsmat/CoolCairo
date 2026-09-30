using System.Collections;
using UnityEngine;

namespace CoolCairo
{
    // Looks at the globe from above a (lat, lon) point. Drag to rotate, scroll to zoom.
    public class GlobeCamera : MonoBehaviour
    {
        [SerializeField] float minDistance = 1.25f, maxDistance = 4.5f;
        [SerializeField] float dragSpeed = 0.15f, zoomSpeed = 0.1f;

        public float Lat { get; private set; } = 20f;
        public float Lon { get; private set; } = 10f;
        public float Distance { get; private set; } = 3.6f;
        public bool UserControl { get; set; }
        public float AutoRotateDegPerSec { get; set; }
        public bool Busy { get; private set; }

        void LateUpdate()
        {
            if (!Busy)
            {
                Lon += AutoRotateDegPerSec * Time.deltaTime;
                if (UserControl)
                {
                    if (Input.GetMouseButton(0) || Input.GetMouseButton(1))
                    {
                        float k = dragSpeed * (Distance - 0.9f) * 10f;
                        Lon -= Input.GetAxis("Mouse X") * k;
                        Lat = Mathf.Clamp(Lat - Input.GetAxis("Mouse Y") * k, -70f, 75f);
                    }
                    float scroll = Input.mouseScrollDelta.y;
                    if (scroll != 0f)
                        Distance = Mathf.Clamp(Distance * (1f - scroll * zoomSpeed), minDistance, maxDistance);
                }
            }
            Apply();
        }

        void Apply()
        {
            transform.position = Globe.LatLonToPosition(Lat, Lon, Distance);
            transform.LookAt(Vector3.zero, Vector3.up);
        }

        // Smoothly move to look down on (lat, lon) from the given distance.
        public IEnumerator FlyTo(float lat, float lon, float distance, float seconds)
        {
            Busy = true;
            float lat0 = Lat, lon0 = Lon, d0 = Distance;
            float dLon = Mathf.DeltaAngle(lon0, lon);
            for (float t = 0f; t < 1f; t += Time.deltaTime / seconds)
            {
                float s = Mathf.SmoothStep(0f, 1f, t);
                Lat = Mathf.Lerp(lat0, lat, s);
                Lon = lon0 + dLon * s;
                // Zoom on a log scale so the approach feels even from space to street level.
                Distance = Mathf.Exp(Mathf.Lerp(Mathf.Log(d0), Mathf.Log(distance), s));
                yield return null;
            }
            Lat = lat; Lon = lon; Distance = distance;
            Busy = false;
        }
    }
}
