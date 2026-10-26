using System.Collections;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace CoolCairo
{
    // App entry: MENA globe -> choose a live city -> that city's loading screen (satellite archive
    // sync and which data the city has) -> fly-in -> 3D district.
    // IMGUI, styled like the district HUD: dark glass panels, thin cyan outlines with corner
    // brackets, monospaced titles and section labels.
    public class IntroController : MonoBehaviour
    {
        enum Phase { Globe, CityLoading, FlyIn }

        [SerializeField] TextAsset districtJson;
        [SerializeField] GlobeCamera globeCamera;
        [SerializeField] SatelliteOrbits satellites;
        [SerializeField] Material satelliteMaterial;
        [SerializeField] Material markerMaterial;
        [SerializeField] Material flyInMaterial;     // CoolCairo/FadeTexture
        [SerializeField] string districtScene = "Main";
        [SerializeField] Font monoFont;               // DejaVu Sans Mono, as in the district HUD

        // "Coming soon" cities stay greyed out, but with a dark outline and a label backdrop so
        // they stay readable over the bright desert.
        static readonly Color LiveColor = new Color(1f, 0.45f, 0.1f);
        static readonly Color SoonColor = new Color(0.78f, 0.80f, 0.84f);
        static readonly Color OutlineColor = new Color(0.05f, 0.06f, 0.09f);
        const float LiveSize = 0.022f, SoonSize = 0.016f, OutlineScale = 1.6f;

        // Live cities have an analysed district; the rest show where the method scales next.
        static CityCatalog.City[] Cities => CityCatalog.All;
        const float MenaLat = 26f, MenaLon = 30f;

        // Survives returning from the district, so each city's archive sync runs once per launch.
        static readonly Dictionary<string, List<SourceSync>> s_syncs = new Dictionary<string, List<SourceSync>>();
        static bool s_globeSeen;
        const float MaxArchiveWait = 5f;   // seconds the loading screen waits for the live archive
        List<SourceSync> _syncs;
        float _panelAlpha, _curtain;

        // Camera distance (globe radius 1) where the fast approach ends and the slow descent onto
        // the Sentinel-2 close-up begins. FlyInImage is fully faded in by this distance.
        public const float ApproachDistance = 1.12f;
        FlyInImage _flyIn;
        bool _showFlyInCaption;

        Phase _phase;
        DistrictData _cairo, _data;   // _data: the city being loaded (Cairo until one is chosen)
        AsyncOperation _districtLoad;
        float _fadeToBlack;
        readonly List<Transform> _markers = new List<Transform>();
        readonly List<Transform> _outlines = new List<Transform>();
        GUIStyle _title, _subtitle, _body, _small, _bold, _marker, _section, _tile, _exitStyle;
        Texture2D _pixel;

        void Start()
        {
            _cairo = _data = DistrictData.FromJson(districtJson.text);
            _districtLoad = SceneManager.LoadSceneAsync(districtScene);
            _districtLoad.allowSceneActivation = false;
            satellites.Create(_cairo.sources.Select(s => s.satellite).ToList(), satelliteMaterial);
            CreateMarkers();
            // The app opens on the globe: fade in from black on launch, at once when coming back.
            EnterGlobe(immediate: s_globeSeen);
            s_globeSeen = true;
        }

        void EnterGlobe(bool immediate)
        {
            _phase = Phase.Globe;
            _curtain = immediate ? 0f : 1f;
            globeCamera.AutoRotateDegPerSec = 0f;
            StartCoroutine(RevealGlobe());
        }

        IEnumerator RevealGlobe()
        {
            satellites.SetVisible(true);
            while (_curtain > 0f)
            {
                _curtain = Mathf.Max(0f, _curtain - Time.deltaTime / 0.8f);
                yield return null;
            }
            yield return globeCamera.FlyTo(MenaLat, MenaLon, 2.1f, 2.2f);
            globeCamera.UserControl = true;
        }

        // A live city was chosen: turn the globe to it while its loading screen checks the
        // satellite archive and lists the data this city has, then fly in.
        IEnumerator CityLoading(CityCatalog.City city)
        {
            string json = CityCatalog.Json(city, districtJson);
            if (json == null)
            {
                _toast = $"{city.Name}: district data missing from this build.";
                _toastUntil = Time.time + 3.5f;
                yield break;
            }
            _phase = Phase.CityLoading;
            globeCamera.UserControl = false;
            LoadingDone = false;
            _data = DistrictData.FromJson(json);
            CityCatalog.Select(city, json);

            if (_flyIn != null) Destroy(_flyIn.gameObject);
            _flyIn = new GameObject("FlyInImage", typeof(MeshFilter), typeof(MeshRenderer)).AddComponent<FlyInImage>();
            _flyIn.Init(_data.flyIn, flyInMaterial, globeCamera, city.Key);
            StartCoroutine(_flyIn.Download());
            StartCoroutine(globeCamera.FlyTo(city.Lat, city.Lon, 1.7f, 1.6f));

            for (float t = 0f; t < 1f; t += Time.deltaTime / 0.3f) { _panelAlpha = t; yield return null; }
            _panelAlpha = 1f;

            if (!s_syncs.TryGetValue(city.Key, out _syncs))
            {
                _syncs = _data.sources.Select(s => new SourceSync { Source = s }).ToList();
                s_syncs[city.Key] = _syncs;
                // Start each satellite's check a moment apart so progress reads one line at a time.
                foreach (var sync in _syncs)
                {
                    StartCoroutine(ArchiveSync.Run(sync, _data.previewBbox, city.Key));
                    yield return new WaitForSeconds(0.15f);
                }
                // The live archive check is a bonus, not a gate: on a slow connection, go on after
                // a few seconds with the prepared data (the analysis itself is precomputed).
                for (float t = 0f; t < MaxArchiveWait && _syncs.Any(s => s.State < SyncState.Complete); t += Time.deltaTime)
                    yield return null;
                foreach (var s in _syncs.Where(s => s.State < SyncState.Complete)) s.State = SyncState.Offline;
            }
            while (_districtLoad.progress < 0.9f) yield return null;

            LoadingDone = true;
            yield return new WaitForSeconds(1.2f); // Let the completed list be read.
            for (float t = 1f; t > 0f; t -= Time.deltaTime / 0.35f) { _panelAlpha = t; yield return null; }
            _panelAlpha = 0f;
            while (globeCamera.Busy) yield return null;
            yield return FlyIntoCity(city);
        }

        IEnumerator FlyIntoCity(CityCatalog.City city)
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
            // narrow the field of view like a zoom lens until the ~23 km Sentinel-2 close-up fills
            // the whole width (at 11 degrees the soft 500 m Blue Marble still showed at the sides).
            StartCoroutine(ZoomLens(Camera.main, 60f, 5f, 3.0f));
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

        GameObject MarkerSphere(string name, CityCatalog.City city, float radius, float size, Color color)
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
            // Pulse the live markers (and their outlines), each a little out of step.
            for (int i = 0; i < Cities.Length; i++)
            {
                if (!Cities[i].Live) continue;
                float live = LiveSize * (1f + 0.25f * Mathf.Sin(Time.time * 4f + i * 0.9f));
                _markers[i].localScale = Vector3.one * live;
                _outlines[i].localScale = Vector3.one * live * OutlineScale;
                // Keep the outline sunk as it grows, or its top would cover the dot at peak pulse.
                _outlines[i].position = _markers[i].position.normalized * OutlineCentre(live);
            }

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
        // The chosen city's archive rows are done and the list holds still before the fade.
        public bool LoadingDone { get; private set; }
        public bool ReadyForInput => _phase == Phase.Globe && _curtain <= 0f && !globeCamera.Busy;

        // Index into CityCatalog.All (0 = Cairo).
        public void ChooseCity(int index) => OnCityChosen(index);

        void OnCityChosen(int index)
        {
            if (_phase != Phase.Globe) return;
            var city = Cities[index];
            if (city.Live) StartCoroutine(CityLoading(city));
            else { _toast = $"{city.Name}: coming soon — the pipeline runs on any city with Landsat and Sentinel-2 coverage."; _toastUntil = Time.time + 3.5f; }
        }

        // ---------- UI ----------

        void OnGUI()
        {
            EnsureStyles();
            if (_curtain > 0f) Fill(new Rect(0, 0, Screen.width, Screen.height), new Color(0.01f, 0.015f, 0.03f, _curtain));
            if (_phase == Phase.CityLoading || _panelAlpha > 0f) DrawLoading(_panelAlpha);
            if (_phase == Phase.Globe && _curtain <= 0f) DrawGlobeUI();
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

            // Wide enough that every "dates" line fits on one line.
            const float w = 860f;
            var syncs = _syncs ?? new List<SourceSync>();
            bool hasEnmap = syncs.Any(s => s.Source.satellite == "EnMAP");
            int rows = syncs.Count + (hasEnmap ? 0 : 1) + 4;
            float h = Mathf.Min(Screen.height - 32f, 214f + rows * 62f);
            var panel = new Rect((Screen.width - w) / 2f, (Screen.height - h) / 2f, w, h);
            Panel(panel);

            GUILayout.BeginArea(new Rect(panel.x + 28, panel.y + 22, w - 56, h - 44));
            GUILayout.Label($"[ COOLCAIRO <color=#4FD6FF>//</color> {_data.name.ToUpperInvariant()} ]", _title);
            GUILayout.Label($"Urban heat decision support  ·  {(CityCatalog.CairoSelected ? "East Cairo" : _data.CityName)}", _subtitle);
            GUILayout.Space(14);
            GUILayout.Label("01 // SATELLITE ARCHIVE AND DATA FOR THIS CITY", _section);
            GUILayout.Space(6);

            foreach (var s in syncs) SourceRow(s);
            if (!hasEnmap) // EnMAP was not processed for this city.
                StaticRow("EnMAP", "HSI", "Hyperspectral heat drivers  ·  no cloud-free EnMAP scene over this district yet",
                          "Not available", Idle);
            BuildingsRow();
            GrowthRow();
            StaticRow("WorldPop 2024", "POP", $"Residents per block (census counts mapped onto satellite-detected buildings)  ·  " +
                      $"{_data.blocks.population.Where(p => p > 0).Sum():N0} residents in the district", "✓ Ready", Good);
            bool ready = _districtLoad.progress >= 0.9f;
            StaticRow($"{_data.name} district", "3D",
                $"{_data.BlockCount} blocks · {_data.buildings.count:N0} buildings · model R² {_data.model.r2SpatialCv:0.00}",
                ready ? "✓ Ready" : "Preparing…", ready ? Good : Busy);

            GUILayout.FlexibleSpace();
            float done = syncs.Count(s => s.State >= SyncState.Complete) + (ready ? 1 : 0);
            var bar = GUILayoutUtility.GetRect(w - 56, 6);
            Fill(bar, new Color(1, 1, 1, 0.12f));
            Fill(new Rect(bar.x, bar.y, bar.width * done / (syncs.Count + 1), bar.height), Good);
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
            // EnMAP has no preview image: a tile with "HSI" (hyperspectral imager) instead.
            Row(s.Preview, src.satellite == "EnMAP" ? "HSI" : "SAT", src.satellite, detail, status, color);
        }

        // Where the 3D buildings and their heights come from; heights mostly at the default are
        // flagged, since they make the model's height term an estimate.
        void BuildingsRow()
        {
            var hs = _data.heightSources;
            string detail = $"{_data.buildings.count:N0} OpenStreetMap footprints  ·  heights: ";
            if (!_data.HasHeightSources) { detail += "OSM tags and Google Open Buildings 2.5D"; StaticRow("Buildings", "BLD", detail, "✓ Ready", Good); return; }
            var parts = new List<string>();
            if (hs.openBuildings >= 0.005f) parts.Add($"{hs.openBuildings:P0} Google Open Buildings 2.5D");
            if (hs.osmHeight + hs.osmLevels >= 0.005f) parts.Add($"{hs.osmHeight + hs.osmLevels:P0} OSM tags");
            if (hs.@default >= 0.005f) parts.Add($"{hs.@default:P0} default 5 storeys");
            detail += string.Join(", ", parts);
            bool estimated = hs.@default > 0.5f;
            StaticRow("Buildings", "BLD", detail, estimated ? "Heights estimated" : "✓ Ready", estimated ? Warn : Good);
        }

        void GrowthRow()
        {
            if (_data.HasGrowth)
            {
                var g = _data.growth;
                StaticRow("Urban growth", "GRW", $"Google Open Buildings Temporal {g.firstYear} → {g.lastYear}  ·  " +
                          $"{g.newBlocks} new, {g.denserBlocks} denser blocks in the district", "✓ Ready", Good);
            }
            else
            {
                // Open Buildings covers the city (heights came from it) but its growth layers are
                // not processed yet; otherwise it has no tiles here at all.
                bool covered = _data.HasHeightSources && _data.heightSources.openBuildings > 0f;
                StaticRow("Urban growth", "GRW", covered
                              ? "Google Open Buildings Temporal covers this city; its 2016–2023 growth layers are not processed yet"
                              : "Needs Google Open Buildings Temporal, which has no tiles for this city",
                          "Not available", Idle);
            }
        }

        void StaticRow(string name, string code, string detail, string status, Color color) =>
            Row(null, code, name, detail, status, color);

        // A row: preview thumbnail (or a coded tile when there is none), name and detail, status.
        void Row(Texture2D thumb, string code, string name, string detail, string status, Color statusColor)
        {
            GUILayout.BeginHorizontal(GUILayout.Height(58));
            var t = GUILayoutUtility.GetRect(52, 52, GUILayout.Width(52));
            if (thumb != null) GUI.DrawTexture(t, thumb, ScaleMode.ScaleAndCrop);
            else
            {
                Fill(t, new Color(Cyan.r, Cyan.g, Cyan.b, 0.10f));
                Outline(t, new Color(Cyan.r, Cyan.g, Cyan.b, 0.45f));
                GUI.Label(t, code, _tile);
            }
            GUILayout.Space(12);
            GUILayout.BeginVertical();
            GUILayout.Label(name, _bold);
            GUILayout.Label(detail, _small);
            GUILayout.EndVertical();
            GUILayout.FlexibleSpace();
            var prev = GUI.contentColor;
            GUI.contentColor = statusColor;
            GUILayout.Label(status, _body, GUILayout.Width(220));
            GUI.contentColor = prev;
            GUILayout.EndHorizontal();
        }

        void DrawGlobeUI()
        {
            var head = new Rect(16, 16, 620, 92);
            Panel(head);
            GUI.Label(new Rect(head.x + 22, head.y + 12, 600, 40), "[ COOLCAIRO <color=#4FD6FF>//</color> MENA ]", _title);
            GUI.Label(new Rect(head.x + 24, head.y + 54, 600, 30), "Urban heat across the Middle East & North Africa", _subtitle);

            // Exit, bottom right; a second click within 3 s quits (QuitGuard).
            var exit = new Rect(Screen.width - 136, Screen.height - 60, 120, 40);
            Panel(exit, brackets: false);
            if (GUI.Button(exit, QuitGuard.Armed ? "<color=#FF8A3D>CONFIRM?</color>" : "EXIT", _exitStyle)) QuitGuard.Press();

            // City list: live districts first, then where the method scales next.
            var list = new Rect(Screen.width - 376, 16, 360, 50 + Cities.Length * 28);
            Panel(list);
            GUI.Label(new Rect(list.x + 16, list.y + 12, 320, 22), "01 // CITIES", _section);
            for (int i = 0; i < Cities.Length; i++)
            {
                var row = new Rect(list.x + 12, list.y + 40 + i * 28, list.width - 24, 26);
                var c = Cities[i];
                var prev = GUI.contentColor;
                GUI.contentColor = c.Live ? new Color(1f, 0.6f, 0.3f) : SoonColor;
                if (GUI.Button(row, $"{(c.Live ? "●" : "○")}  {c.Label}   {(c.Live ? "LIVE" : "coming soon")}", _body) && !globeCamera.Busy)
                    OnCityChosen(i);
                GUI.contentColor = prev;
            }

            // Labels next to the markers facing the camera. Placed in list order (Cairo first) at
            // the first free spot: right, left, above, below the dot. A label with no free spot
            // is left out (the Gulf cities sit close together); the city list still names it.
            var cam = Camera.main;
            var placed = new List<Rect>();
            for (int i = 0; i < Cities.Length; i++)
            {
                var p = _markers[i].position;
                if (Vector3.Dot(p.normalized, (cam.transform.position - p).normalized) < 0.1f) continue;
                var sp = cam.WorldToScreenPoint(p);
                var style = Cities[i].Live ? _bold : _marker;
                var content = new GUIContent(Cities[i].Name);
                var size = style.CalcSize(content);
                float x = sp.x, y = Screen.height - sp.y, lw = size.x + 10, lh = size.y + 2;
                var spots = new[]
                {
                    new Rect(x + 12, y - lh / 2f, lw, lh), new Rect(x - 12 - lw, y - lh / 2f, lw, lh),
                    new Rect(x - lw / 2f, y - 12 - lh, lw, lh), new Rect(x - lw / 2f, y + 12, lw, lh),
                };
                int free = System.Array.FindIndex(spots, s => !placed.Any(o => o.Overlaps(Grow(s, 2f))));
                if (free < 0) continue;
                var r = spots[free];
                placed.Add(r);
                // Dark backdrop so labels read over the bright desert; grey text keeps the
                // "coming soon" cities visibly greyed out next to the live one.
                Fill(r, new Color(0.02f, 0.03f, 0.06f, 0.72f));
                GUI.Label(new Rect(r.x + 5, r.y + 1, size.x, size.y), content, style);
            }

            var hint = new Rect(16, Screen.height - 52, 760, 36);
            Panel(hint, brackets: false);
            GUI.Label(new Rect(hint.x + 16, hint.y + 9, 740, 22),
                      "<color=#E6F1FF>DRAG</color> rotate  ·  <color=#E6F1FF>SCROLL</color> zoom  ·  " +
                      "<color=#E6F1FF>CLICK A LIVE CITY</color> open its 3D district", _section);
            if (Time.time < _toastUntil)
                GUI.Label(new Rect(Screen.width / 2f - 320, Screen.height - 90, 640, 40), _toast, _body);
        }

        static Rect Grow(Rect r, float by) => new Rect(r.x - by, r.y - by, r.width + 2 * by, r.height + 2 * by);

        static readonly Color Cyan = new Color(0.31f, 0.84f, 1f);

        // HUD panel: dark glass, thin cyan outline, brighter corner brackets.
        void Panel(Rect r, bool brackets = true)
        {
            Fill(r, new Color(0.02f, 0.043f, 0.078f, 0.9f));
            Outline(r, new Color(Cyan.r, Cyan.g, Cyan.b, 0.28f));
            if (!brackets) return;
            var c = new Color(Cyan.r, Cyan.g, Cyan.b, 0.95f);
            const float len = 14f, th = 2f;
            Fill(new Rect(r.xMin, r.yMin, len, th), c); Fill(new Rect(r.xMin, r.yMin, th, len), c);
            Fill(new Rect(r.xMax - len, r.yMin, len, th), c); Fill(new Rect(r.xMax - th, r.yMin, th, len), c);
            Fill(new Rect(r.xMin, r.yMax - th, len, th), c); Fill(new Rect(r.xMin, r.yMax - len, th, len), c);
            Fill(new Rect(r.xMax - len, r.yMax - th, len, th), c); Fill(new Rect(r.xMax - th, r.yMax - len, th, len), c);
        }

        void Outline(Rect r, Color c)
        {
            Fill(new Rect(r.x, r.y, r.width, 1), c);
            Fill(new Rect(r.x, r.yMax - 1, r.width, 1), c);
            Fill(new Rect(r.x, r.y, 1, r.height), c);
            Fill(new Rect(r.xMax - 1, r.y, 1, r.height), c);
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
                new GUIStyle(GUI.skin.label) { fontSize = size, fontStyle = fs, normal = { textColor = c }, wordWrap = true, richText = true };
            _title = Make(26, FontStyle.Bold, new Color(0.9f, 0.945f, 1f));
            _title.font = monoFont;
            _subtitle = Make(16, FontStyle.Normal, new Color(0.66f, 0.72f, 0.80f));
            _section = Make(12, FontStyle.Bold, Cyan);
            _section.font = monoFont;
            _tile = Make(13, FontStyle.Bold, Cyan);
            _tile.font = monoFont;
            _tile.alignment = TextAnchor.MiddleCenter;
            _body = Make(14, FontStyle.Normal, Color.white);
            _bold = Make(15, FontStyle.Bold, Color.white);
            _exitStyle = new GUIStyle(_bold) { alignment = TextAnchor.MiddleCenter, wordWrap = false };
            _small = Make(12, FontStyle.Normal, new Color(0.65f, 0.7f, 0.8f));
            _body.hover.textColor = Color.white;
            _marker = Make(13, FontStyle.Normal, new Color(0.80f, 0.82f, 0.86f));
            _marker.wordWrap = false;
        }
    }
}
