using System.Collections;
using System.Globalization;
using System.Linq;
using UnityEngine;
using UnityEngine.Networking;

namespace CoolCairo
{
    // Sharp Sentinel-2 image of Cairo laid on the globe's surface. The Blue Marble texture is
    // ~7 km per pixel, so close to the ground it turns to mush; this 10 m image (downloaded from
    // the Planetary Computer archive at startup) fades in as the camera descends.
    // Offline: nothing is shown and the fly-in simply fades as before.
    [RequireComponent(typeof(MeshFilter), typeof(MeshRenderer))]
    public class FlyInImage : MonoBehaviour
    {
        const string DataBbox = "https://planetarycomputer.microsoft.com/api/data/v1/item/bbox/";
        const float SurfaceRadius = 1.0004f;  // Just above the globe mesh.
        const float FadeStart = 1.3f, FadeFull = IntroController.ApproachDistance;  // Camera distances (globe radius = 1).
        const int GridSteps = 24;

        // Kept for the session, so returning to the globe does not download it again.
        static Texture2D s_cached;

        FlyInInfo _info;
        GlobeCamera _camera;
        Material _material;

        public bool Ready { get; private set; }

        public void Init(FlyInInfo info, Material template, GlobeCamera globeCamera)
        {
            _info = info;
            _camera = globeCamera;
            _material = new Material(template);
            _material.SetFloat("_Alpha", 0f);
            GetComponent<MeshRenderer>().sharedMaterial = _material;
            if (info != null && info.bbox != null && info.bbox.Length == 4)
                GetComponent<MeshFilter>().sharedMesh = BuildPatch(info.bbox);
        }

        public IEnumerator Download()
        {
            if (_info == null || string.IsNullOrEmpty(_info.item) || _info.bbox?.Length != 4) yield break;
            if (s_cached != null)
            {
                _material.SetTexture("_BaseMap", s_cached);
                Ready = true;
                yield break;
            }
            string box = string.Join(",", _info.bbox.Select(v => v.ToString(CultureInfo.InvariantCulture)));
            string url = $"{DataBbox}{box}/1024x1024.png?collection={_info.collection}&item={_info.item}&{_info.query}";
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
            s_cached = tex;
            _material.SetTexture("_BaseMap", tex);
            Ready = true;
            Debug.Log($"Fly-in image ready: Sentinel-2 {_info.date}, {tex.width}x{tex.height}.");
        }

        void LateUpdate()
        {
            float alpha = Ready ? Mathf.SmoothStep(0f, 1f, Mathf.InverseLerp(FadeStart, FadeFull, _camera.Distance)) : 0f;
            _material.SetFloat("_Alpha", alpha);
        }

        // Curved patch on the sphere covering the lon/lat box, UVs matching the image.
        static Mesh BuildPatch(float[] bbox)
        {
            float minLon = bbox[0], minLat = bbox[1], maxLon = bbox[2], maxLat = bbox[3];
            int n = GridSteps + 1;
            var verts = new Vector3[n * n];
            var uvs = new Vector2[n * n];
            for (int i = 0; i < n; i++)
            for (int j = 0; j < n; j++)
            {
                float u = (float)j / GridSteps, v = (float)i / GridSteps;
                verts[i * n + j] = Globe.LatLonToPosition(Mathf.Lerp(minLat, maxLat, v), Mathf.Lerp(minLon, maxLon, u), SurfaceRadius);
                uvs[i * n + j] = new Vector2(u, v);
            }
            // Same winding as Globe: seen from outside, +lon right and +lat up.
            var tris = new int[GridSteps * GridSteps * 6];
            int t = 0;
            for (int i = 0; i < GridSteps; i++)
            for (int j = 0; j < GridSteps; j++)
            {
                int a = i * n + j, b = a + 1, d = a + n, c = d + 1;
                tris[t++] = a; tris[t++] = d; tris[t++] = c;
                tris[t++] = a; tris[t++] = c; tris[t++] = b;
            }
            var mesh = new Mesh { name = "FlyInPatch", vertices = verts, uv = uvs, triangles = tris };
            mesh.RecalculateBounds();
            return mesh;
        }
    }
}
