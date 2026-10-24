using System.Collections;
using System.Globalization;
using System.Linq;
using UnityEngine;
using UnityEngine.Networking;

namespace CoolCairo
{
    // Sharp Sentinel-2 image of the chosen city laid on the globe's surface. Even the 500 m Blue Marble
    // patch (GlobePatch) turns soft in the last kilometres; this 10 m image (downloaded from
    // the Planetary Computer archive at startup) fades in as the camera descends.
    // Offline: nothing is shown and the fly-in simply fades as before.
    [RequireComponent(typeof(MeshFilter), typeof(MeshRenderer))]
    public class FlyInImage : MonoBehaviour
    {
        const string DataBbox = "https://planetarycomputer.microsoft.com/api/data/v1/item/bbox/";
        const float SurfaceRadius = 1.0004f;  // Above the globe mesh and the GlobePatch.
        const float FadeStart = 1.3f, FadeFull = IntroController.ApproachDistance;  // Camera distances (globe radius = 1).
        const int GridSteps = 24;

        // Kept for the session per image (one per city), so returning to the globe does not
        // download it again. One shared slot showed the previous city's image on the next city.
        static readonly System.Collections.Generic.Dictionary<string, Texture2D> s_cache =
            new System.Collections.Generic.Dictionary<string, Texture2D>();

        FlyInInfo _info;
        GlobeCamera _camera;
        Material _material;

        public bool Ready { get; private set; }

        public void Init(FlyInInfo info, Material template, GlobeCamera globeCamera, string cityKey = "cairo")
        {
            _info = info;
            _camera = globeCamera;
            _material = new Material(template);
            _material.SetFloat("_Alpha", 0f);
            GetComponent<MeshRenderer>().sharedMaterial = _material;
            if (info != null && info.bbox != null && info.bbox.Length == 4)
                GetComponent<MeshFilter>().sharedMesh = Globe.BuildPatch(info.bbox, SurfaceRadius, GridSteps, "FlyInPatch");
            // The same image, downloaded once and shipped with the app (analysis/report/app_images.py):
            // the fly-in then works offline and on slow connections, where the live render timed out.
            var bundled = Resources.Load<Texture2D>($"Districts/{cityKey}/flyin");
            if (bundled != null)
            {
                bundled.wrapMode = TextureWrapMode.Clamp;
                _material.SetTexture("_BaseMap", bundled);
                Ready = true;
            }
        }

        public IEnumerator Download()
        {
            if (Ready) yield break;   // shipped with the app
            if (_info == null || string.IsNullOrEmpty(_info.item) || _info.bbox?.Length != 4) yield break;
            string box = string.Join(",", _info.bbox.Select(v => v.ToString(CultureInfo.InvariantCulture)));
            string url = $"{DataBbox}{box}/1024x1024.png?collection={_info.collection}&item={_info.item}&{_info.query}";
            if (s_cache.TryGetValue(url, out var cached))
            {
                _material.SetTexture("_BaseMap", cached);
                Ready = true;
                yield break;
            }
            using var req = UnityWebRequestTexture.GetTexture(url);
            req.timeout = 30;
            yield return req.SendWebRequest();
            if (req.result != UnityWebRequest.Result.Success)
            {
                Debug.LogWarning($"Fly-in image download failed ({req.error}); using plain fade.");
                yield break;
            }
            var tex = DownloadHandlerTexture.GetContent(req);
            tex.wrapMode = TextureWrapMode.Clamp;
            tex.anisoLevel = 8;
            s_cache[url] = tex;
            if (this == null) yield break;   // left for another city while downloading
            _material.SetTexture("_BaseMap", tex);
            Ready = true;
            Debug.Log($"Fly-in image ready: Sentinel-2 {_info.date}, {tex.width}x{tex.height}.");
        }

        void LateUpdate()
        {
            float alpha = Ready ? Mathf.SmoothStep(0f, 1f, Mathf.InverseLerp(FadeStart, FadeFull, _camera.Distance)) : 0f;
            _material.SetFloat("_Alpha", alpha);
        }
    }
}
