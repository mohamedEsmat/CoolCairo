using UnityEngine;

namespace CoolCairo
{
    // 500 m Blue Marble image of Egypt and the Middle East laid over the 2.4 km globe texture, so
    // the fly-in to Cairo stays sharp until the Sentinel-2 close-up takes over. Same NASA mosaic
    // as the globe, so colours match and the soft edge hides the change in resolution.
    // Made by analysis/globe_textures.py; Bbox must match MENA_BBOX there.
    [RequireComponent(typeof(MeshFilter), typeof(MeshRenderer))]
    public class GlobePatch : MonoBehaviour
    {
        public static readonly float[] Bbox = { 20f, 18f, 43f, 40f };  // min lon, min lat, max lon, max lat
        const float SurfaceRadius = 1.0002f;  // Above the globe mesh, below the fly-in image.
        const int GridSteps = 64;

        void Awake() =>
            GetComponent<MeshFilter>().sharedMesh = Globe.BuildPatch(Bbox, SurfaceRadius, GridSteps, "GlobePatch");
    }
}
