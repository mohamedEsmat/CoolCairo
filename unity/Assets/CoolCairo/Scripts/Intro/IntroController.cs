using System.Collections;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace CoolCairo
{
    // App entry: satellite archive sync (loading screen) -> MENA globe -> fly-in -> 3D district.
    // Placeholder IMGUI styling; the layout and the information shown are the contract for the
    // designed UI.
    public class IntroController : MonoBehaviour
    {
        enum Phase { Loading, Globe, FlyIn }

        [SerializeField] TextAsset districtJson;
        [SerializeField] GlobeCamera globeCamera;
        [SerializeField] SatelliteOrbits satellites;
        [SerializeField] Material satelliteMaterial;
        [SerializeField] Material markerMaterial;
        [SerializeField] Material flyInMaterial;     // CoolCairo/FadeTexture
        [SerializeField] string districtScene = "Main";

        // "Coming soon" cities stay greyed out, but with a dark outline and a label backdrop so
        // they stay readable over the bright desert.
        static readonly Color LiveColor = new Color(1f, 0.45f, 0.1f);
        static readonly Color SoonColor = new Color(0.78f, 0.80f, 0.84f);
        static readonly Color OutlineColor = new Color(0.05f, 0.06f, 0.09f);
        const float LiveSize = 0.022f, SoonSize = 0.016f, OutlineScale = 1.6f;

        struct City { public string Name; public float Lat, Lon; public bool Live; }

        // Nasr City is the one analysed district; the rest show where the method scales next.
        static readonly City[] Cities =
        {
            new City { Name = "Cairo — Nasr City", Lat = 30.06f, Lon = 31.33f, Live = true },
            new City { Name = "Abu Dhabi", Lat = 24.45f, Lon = 54.38f },
            new City { Name = "Dubai", Lat = 25.20f, Lon = 55.27f },
            new City { Name = "Riyadh", Lat = 24.71f, Lon = 46.68f },
            new City { Name = "Doha", Lat = 25.29f, Lon = 51.53f },
            new City { Name = "Kuwait City", Lat = 29.38f, Lon = 47.99f },
            new City { Name = "Muscat", Lat = 23.59f, Lon = 58.41f },
            new City { Name = "Amman", Lat = 31.95f, Lon = 35.93f },
            new City { Name = "Beirut", Lat = 33.89f, Lon = 35.50f },
            new City { Name = "Baghdad", Lat = 33.31f, Lon = 44.36f },
            new City { Name = "Tunis", Lat = 36.81f, Lon = 10.18f },
            new City { Name = "Algiers", Lat = 36.75f, Lon = 3.06f },
            new City { Name = "Casablanca", Lat = 33.57f, Lon = -7.59f },
        };
        const float MenaLat = 26f, MenaLon = 30f;

        // Survives returning from the district, so the archive sync runs once per app launch.
        static List<SourceSync> s_syncs;

        // Camera distance (globe radius 1) where the fast approach ends and the slow descent onto
        // the Sentinel-2 close-up begins. FlyInImage is fully faded in by this distance.
        public const float ApproachDistance = 1.12f;
        FlyInImage _flyIn;
        bool _showFlyInCaption;

        Phase _phase;
        DistrictData _data;
        AsyncOperation _districtLoad;
        float _overlayAlpha = 1f, _fadeToBlack;
        readonly List<Transform> _markers = new List<Transform>();
        readonly List<Transform> _outlines = new List<Transform>();
        GUIStyle _title, _subtitle, _body, _small, _bold, _marker;
        Texture2D _pixel;

        void Start()
        {
            _data = DistrictData.FromJson(districtJson.text);
            _districtLoad = SceneManager.LoadSceneAsync(districtScene);
            _districtLoad.allowSceneActivation = false;
            satellites.Create(_data.sources.Select(s => s.satellite).ToList(), satelliteMaterial);
            CreateMarkers();
            _flyIn = new GameObject("FlyInImage", typeof(MeshFilter), typeof(MeshRenderer)).AddComponent<FlyInImage>();
            _flyIn.Init(_data.flyIn, flyInMaterial, globeCamera);
            StartCoroutine(_flyIn.Download());

            if (s_syncs != null) EnterGlobe(immediate: true);
            else StartCoroutine(LoadingSequence());
        }

        IEnumerator LoadingSequence()
        {
            _phase = Phase.Loading;
            globeCamera.AutoRotateDegPerSec = 6f;
            s_syncs = _data.sources.Select(s => new SourceSync { Source = s }).ToList();

            // Start each satellite's sync a moment apart so progress reads one line at a time.
            var running = new List<Coroutine>();
            foreach (var sync in s_syncs)
            {
                running.Add(StartCoroutine(ArchiveSync.Run(sync, _data.previewBbox)));
                yield return new WaitForSeconds(0.35f);
            }
            foreach (var c in running) yield return c;
            while (_districtLoad.progress < 0.9f) yield return null;

            yield return new WaitForSeconds(1.5f); // Let the completed list be read.
            EnterGlobe(immediate: false);
        }

        void EnterGlobe(bool immediate)
        {
            _phase = Phase.Globe;
            if (immediate) _overlayAlpha = 0f;
            globeCamera.AutoRotateDegPerSec = 0f;
            StartCoroutine(RevealGlobe());
        }

        IEnumerator RevealGlobe()
        {
            satellites.SetVisible(true);
            while (_overlayAlpha > 0f)
            {
                _overlayAlpha = Mathf.Max(0f, _overlayAlpha - Time.deltaTime / 0.8f);
                yield return null;
            }
            yield return globeCamera.FlyTo(MenaLat, MenaLon, 2.1f, 2.2f);
            globeCamera.UserControl = true;
        }

        IEnumerator FlyIntoCity(City city)
        {
            _phase = Phase.FlyIn;
            globeCamera.UserControl = false;
            satellites.SetVisible(false);
            // Stage 1: fast approach over the Blue Marble to just above the city.
            yield return globeCamera.FlyTo(city.Lat, city.Lon, ApproachDistance, 2.0f);
            // Stage 2: slow descent; the Sentinel-2 close-up is fully visible from the start of it.
            // Markers are ~140 km wide at globe scale, so they would cover the close-up: hide them.
            foreach (var t in _markers.Concat(_outlines)) t.gameObject.SetActive(false);
            _showFlyInCaption = _flyIn != null && _flyIn.Ready;
            // Stop at 1.02 (ground well beyond the near clip plane; closer, the globe vanished) and
            // narrow the field of view like a zoom lens so the Sentinel-2 close-up still fills the view.
            StartCoroutine(ZoomLens(Camera.main, 60f, 11f, 3.0f));
            yield return globeCamera.FlyTo(city.Lat, city.Lon, 1.02f, 3.0f);
            yield return new WaitForSeconds(0.4f);
            for (float t = 0f; t < 1f; t += Time.deltaTime / 0.6f)
            {
                _fadeToBlack = t;
                yield return null;
            }
            _fadeToBlack = 1f;
            _districtLoad.allowSceneActivation = true;
        }

        static IEnumerator ZoomLens(Camera cam, float fromFov, float toFov, float seconds)
        {
            for (float t = 0f; t < 1f; t += Time.deltaTime / seconds)
            {
                cam.fieldOfView = Mathf.Lerp(fromFov, toFov, Mathf.SmoothStep(0f, 1f, t));
                yield return null;
            }
            cam.fieldOfView = toFov;
        }

        void CreateMarkers()
        {
            foreach (var city in Cities)
            {
                float size = city.Live ? LiveSize : SoonSize;
                // Dark outline: a larger sphere sunk below the coloured dot, so only a ring shows
                // around it. Its top must stay under the dot's top or it would swallow the dot.
                float outlineRadius = OutlineCentre(size);
                var outline = MarkerSphere($"{city.Name} outline", city, outlineRadius, size * OutlineScale, OutlineColor);
                Destroy(outline.GetComponent<Collider>()); // Clicks go to the dot itself.
                _outlines.Add(outline.transform);
                _markers.Add(MarkerSphere(city.Name, city, DotCentre, size, city.Live ? LiveColor : SoonColor).transform);
            }
        }

        const float DotCentre = 1.003f;

        // Distance from the globe centre for the outline sphere: its top sits just below the
        // dot's top (dot top = DotCentre + size/2, outline top = centre + OutlineScale*size/2).
        static float OutlineCentre(float size) => DotCentre + size / 2f - OutlineScale * size / 2f - 0.0006f;

        GameObject MarkerSphere(string name, City city, float radius, float size, Color color)
        {
            var go = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            go.name = name;
            go.transform.SetParent(transform, false);
            go.transform.position = Globe.LatLonToPosition(city.Lat, city.Lon, radius);
            go.transform.localScale = Vector3.one * size;
            var r = go.GetComponent<MeshRenderer>();
            r.sharedMaterial = markerMaterial;
            var block = new MaterialPropertyBlock();
            block.SetColor("_BaseColor", color);
            r.SetPropertyBlock(block);
            return go;
        }

        void Update()
        {
            // Pulse the live marker (and its outline).
            float live = LiveSize * (1f + 0.25f * Mathf.Sin(Time.time * 4f));
            _markers[0].localScale = Vector3.one * live;
            _outlines[0].localScale = Vector3.one * live * OutlineScale;
            // Keep the outline sunk as it grows, or its top would cover the dot at peak pulse.
            _outlines[0].position = _markers[0].position.normalized * OutlineCentre(live);

            if (_phase == Phase.Globe && !globeCamera.Busy && Input.GetMouseButtonUp(0) && !_dragged)
            {
                var ray = Camera.main.ScreenPointToRay(Input.mousePosition);
                if (Physics.Raycast(ray, out var hit, 10f))
                {
                    int i = _markers.IndexOf(hit.transform);
                    if (i >= 0) OnCityChosen(i);
                }
            }
            TrackDrag();
        }

        // A click selects a marker only if the mouse did not move much (otherwise it was a drag).
        bool _dragged;
        Vector3 _downPos;
        void TrackDrag()
        {
            if (Input.GetMouseButtonDown(0)) { _downPos = Input.mousePosition; _dragged = false; }
            if (Input.GetMouseButton(0) && (Input.mousePosition - _downPos).sqrMagnitude > 36f) _dragged = true;
        }

        string _toast;
        float _toastUntil;
        // Globe is shown and accepting clicks (used by AutoTest too).
        public bool ReadyForInput => _phase == Phase.Globe && _overlayAlpha <= 0f && !globeCamera.Busy;

        public void ChooseCity(int index) => OnCityChosen(index);

        void OnCityChosen(int index)
        {
            var city = Cities[index];
            if (city.Live) StartCoroutine(FlyIntoCity(city));
            else { _toast = $"{city.Name}: coming soon — the pipeline runs on any city with Landsat and Sentinel-2 coverage."; _toastUntil = Time.time + 3.5f; }
        }

        // ---------- UI ----------

        void OnGUI()
        {
            EnsureStyles();
            if (_phase == Phase.Loading || _overlayAlpha > 0f) DrawLoading(_overlayAlpha);
            if (_phase == Phase.Globe && _overlayAlpha <= 0f) DrawGlobeUI();
            if (_showFlyInCaption && _data.flyIn != null)
                GUI.Label(new Rect(28, Screen.height - 44, 700, 24),
                          $"Sentinel-2  ·  {_data.flyIn.date}  ·  10 m resolution  ·  Contains modified Copernicus Sentinel data [{_data.flyIn.date.Substring(0, 4)}]", _subtitle);
            if (_fadeToBlack > 0f) Fill(new Rect(0, 0, Screen.width, Screen.height), new Color(0, 0, 0, _fadeToBlack));
        }

        void DrawLoading(float alpha)
        {
            var prev = GUI.color;
            GUI.color = new Color(1, 1, 1, alpha);
            Fill(new Rect(0, 0, Screen.width, Screen.height), new Color(0.02f, 0.03f, 0.06f, 0.55f));

            const float w = 720f;
            bool hasEnmap = s_syncs.Any(s => s.Source.satellite == "EnMAP");
            int rows = s_syncs.Count + (hasEnmap ? 2 : 3);
            float h = 190f + rows * 64f;
            var panel = new Rect((Screen.width - w) / 2f, (Screen.height - h) / 2f, w, h);
            Fill(panel, new Color(0.04f, 0.06f, 0.1f, 0.88f));

            GUILayout.BeginArea(new Rect(panel.x + 28, panel.y + 22, w - 56, h - 44));
            GUILayout.Label("CoolCairo", _title);
            GUILayout.Label("Urban heat decision support  ·  Nasr City, Cairo", _subtitle);
            GUILayout.Space(14);
            GUILayout.Label("DOWNLOADING FROM SATELLITE ARCHIVE", _small);
            GUILayout.Space(6);

            foreach (var s in s_syncs) SourceRow(s);
            if (!hasEnmap) // EnMAP not processed in this build of district.json.
                StaticRow("EnMAP", "Hyperspectral heat drivers", "Not processed", Idle);
            StaticRow("WorldPop 2024", $"Residents per block (census counts mapped onto satellite-detected buildings)  ·  " +
                      $"{_data.blocks.population.Where(p => p > 0).Sum():N0} residents in the district", "✓ Ready", Good);
            bool ready = _districtLoad.progress >= 0.9f;
            StaticRow("Nasr City district",
                $"{_data.BlockCount} blocks · {_data.buildings.count:N0} buildings · model R² {_data.model.r2SpatialCv:0.00}",
                ready ? "✓ Ready" : "Preparing…", ready ? Good : Busy);

            GUILayout.FlexibleSpace();
            float done = s_syncs.Count(s => s.State >= SyncState.Complete) + (ready ? 1 : 0);
            var bar = GUILayoutUtility.GetRect(w - 56, 6);
            Fill(bar, new Color(1, 1, 1, 0.12f));
            Fill(new Rect(bar.x, bar.y, bar.width * done / (s_syncs.Count + 1), bar.height), Good);
            GUILayout.Space(6);
            string enmapNote = _data.hyperspectral != null && _data.hyperspectral.available == 1
                ? $" · DLR EOC Geoservice (EnMAP). {_data.hyperspectral.attribution}." : ".";
            GUILayout.Label("Sources: Microsoft Planetary Computer (USGS Landsat Collection 2, ESA Copernicus Sentinel-2)" +
                            enmapNote + " Analysis precomputed from these scenes.", _small);
            GUILayout.EndArea();
            GUI.color = prev;
        }

        static readonly Color Good = new Color(0.35f, 0.85f, 0.5f), Busy = new Color(0.4f, 0.75f, 1f),
                              Warn = new Color(1f, 0.75f, 0.3f), Idle = new Color(0.6f, 0.6f, 0.65f);

        void SourceRow(SourceSync s)
        {
            var src = s.Source;
            string status = s.State switch
            {
                SyncState.Waiting => "Waiting",
                SyncState.Querying => "Querying archive…",
                SyncState.Downloading => "Downloading preview…",
                SyncState.Complete => $"✓ Completed · {s.Found}/{src.sceneIds.Length} scenes",
                _ => "Offline · using prepared data",
            };
            var color = s.State switch
            {
                SyncState.Complete => Good,
                SyncState.Offline => Warn,
                SyncState.Waiting => Idle,
                _ => Busy,
            };
            var hs = _data.hyperspectral;
            string detail = src.satellite == "EnMAP" && hs != null && hs.available == 1
                ? $"{src.use}  ·  224 bands  ·  {src.firstDate}  ·  explains heat R² {hs.r2Hyperspectral:0.00} vs {hs.r2Multispectral:0.00} multispectral"
                : $"{src.use}  ·  {src.sceneIds.Length} scenes  ·  {src.firstDate} → {src.lastDate}";
            Row(s.Preview, src.satellite, detail, status, color);
        }

        void StaticRow(string name, string detail, string status, Color color) => Row(null, name, detail, status, color);

        void Row(Texture2D thumb, string name, string detail, string status, Color statusColor)
        {
            GUILayout.BeginHorizontal(GUILayout.Height(58));
            var t = GUILayoutUtility.GetRect(52, 52, GUILayout.Width(52));
            if (thumb != null) GUI.DrawTexture(t, thumb, ScaleMode.ScaleAndCrop);
            else Fill(t, new Color(1, 1, 1, 0.06f));
            GUILayout.Space(12);
            GUILayout.BeginVertical();
            GUILayout.Label(name, _bold);
            GUILayout.Label(detail, _small);
            GUILayout.EndVertical();
            GUILayout.FlexibleSpace();
            var prev = GUI.contentColor;
            GUI.contentColor = statusColor;
            GUILayout.Label(status, _body, GUILayout.Width(250));
            GUI.contentColor = prev;
            GUILayout.EndHorizontal();
        }

        void DrawGlobeUI()
        {
            GUI.Label(new Rect(28, 22, 600, 50), "CoolCairo", _title);
            GUI.Label(new Rect(30, 70, 700, 30), "Urban heat across the Middle East & North Africa", _subtitle);

            // City list: live district first, then where the method scales next.
            var list = new Rect(Screen.width - 300, 90, 272, 44 + Cities.Length * 28);
            Fill(list, new Color(0.04f, 0.06f, 0.1f, 0.8f));
            GUI.Label(new Rect(list.x + 16, list.y + 10, 240, 22), "CITIES", _small);
            for (int i = 0; i < Cities.Length; i++)
            {
                var row = new Rect(list.x + 12, list.y + 36 + i * 28, list.width - 24, 26);
                var c = Cities[i];
                var prev = GUI.contentColor;
                GUI.contentColor = c.Live ? new Color(1f, 0.6f, 0.3f) : SoonColor;
                if (GUI.Button(row, $"{(c.Live ? "●" : "○")}  {c.Name}   {(c.Live ? "LIVE" : "coming soon")}", _body) && !globeCamera.Busy)
                    OnCityChosen(i);
                GUI.contentColor = prev;
            }

            // Labels next to the markers facing the camera.
            var cam = Camera.main;
            for (int i = 0; i < Cities.Length; i++)
            {
                var p = _markers[i].position;
                if (Vector3.Dot(p.normalized, (cam.transform.position - p).normalized) < 0.1f) continue;
                var sp = cam.WorldToScreenPoint(p);
                var style = i == 0 ? _bold : _marker;
                var content = new GUIContent(Cities[i].Name);
                var size = style.CalcSize(content);
                var r = new Rect(sp.x + 12, Screen.height - sp.y - size.y / 2f, size.x + 10, size.y + 2);
                // Dark backdrop so labels read over the bright desert; grey text keeps the
                // "coming soon" cities visibly greyed out next to the live one.
                Fill(r, new Color(0.02f, 0.03f, 0.06f, 0.72f));
                GUI.Label(new Rect(r.x + 5, r.y + 1, size.x, size.y), content, style);
            }

            GUI.Label(new Rect(28, Screen.height - 40, 800, 24),
                      "Drag to rotate  ·  Scroll to zoom  ·  Click Cairo to open the 3D district", _small);
            if (Time.time < _toastUntil)
                GUI.Label(new Rect(Screen.width / 2f - 320, Screen.height - 90, 640, 40), _toast, _body);
        }

        void Fill(Rect r, Color c)
        {
            var prev = GUI.color;
            GUI.color = new Color(c.r, c.g, c.b, c.a * prev.a);
            GUI.DrawTexture(r, _pixel);
            GUI.color = prev;
        }

        void EnsureStyles()
        {
            if (_title != null) return;
            _pixel = Texture2D.whiteTexture;
            GUIStyle Make(int size, FontStyle fs, Color c) =>
                new GUIStyle(GUI.skin.label) { fontSize = size, fontStyle = fs, normal = { textColor = c }, wordWrap = true };
            _title = Make(34, FontStyle.Bold, Color.white);
            _subtitle = Make(16, FontStyle.Normal, new Color(0.75f, 0.8f, 0.9f));
            _body = Make(14, FontStyle.Normal, Color.white);
            _bold = Make(15, FontStyle.Bold, Color.white);
            _small = Make(12, FontStyle.Normal, new Color(0.65f, 0.7f, 0.8f));
            _body.hover.textColor = Color.white;
            _marker = Make(13, FontStyle.Normal, new Color(0.80f, 0.82f, 0.86f));
            _marker.wordWrap = false;
        }
    }
}
