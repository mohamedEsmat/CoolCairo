using System.Collections.Generic;
using UnityEngine;

namespace CoolCairo
{
    // One marker per satellite, circling the globe on a sun-synchronous-like polar orbit
    // (Landsat and Sentinel-2 are both ~98 deg inclination). Altitude and speed are illustrative.
    public class SatelliteOrbits : MonoBehaviour
    {
        const float Inclination = 98.2f;
        const float Radius = 1.28f;
        const float SecondsPerOrbit = 14f;

        readonly List<(Transform body, float node, float phase)> _sats = new List<(Transform, float, float)>();

        public IReadOnlyList<(Transform body, float node, float phase)> Satellites => _sats;

        public void Create(IList<string> names, Material material)
        {
            for (int i = 0; i < names.Count; i++)
            {
                var go = GameObject.CreatePrimitive(PrimitiveType.Sphere);
                go.name = names[i];
                Destroy(go.GetComponent<Collider>());
                go.transform.SetParent(transform, false);
                go.transform.localScale = Vector3.one * 0.025f;
                go.GetComponent<MeshRenderer>().sharedMaterial = material;

                var trail = go.AddComponent<TrailRenderer>();
                trail.sharedMaterial = material;
                trail.time = 2.5f;
                trail.widthMultiplier = 0.012f;
                trail.widthCurve = AnimationCurve.Linear(0f, 1f, 1f, 0f);
                trail.minVertexDistance = 0.01f;

                // Spread ascending nodes and phases so the satellites do not overlap.
                _sats.Add((go.transform, 360f * i / names.Count, i * 0.37f));
            }
        }

        public void SetVisible(bool visible) => gameObject.SetActive(visible);

        void Update()
        {
            float t = Time.time / SecondsPerOrbit;
            foreach (var (body, node, phase) in _sats)
            {
                float angle = (t + phase) * 360f;
                var inOrbit = Quaternion.Euler(0f, node, 0f) * Quaternion.Euler(0f, 0f, Inclination)
                              * (Quaternion.Euler(0f, angle, 0f) * Vector3.forward);
                body.localPosition = inOrbit * Radius;
            }
        }
    }
}
