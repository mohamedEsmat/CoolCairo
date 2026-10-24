using System;
using System.Collections;
using System.Globalization;
using System.Linq;
using UnityEngine;
using UnityEngine.Networking;

namespace CoolCairo
{
    public enum SyncState { Waiting, Querying, Downloading, Complete, Offline }

    // Live status of one satellite's data in the loading screen.
    public class SourceSync
    {
        public SourceInfo Source;
        public SyncState State = SyncState.Waiting;
        public int Found;          // Scenes the archive confirmed.
        public Texture2D Preview;  // Real image of the model area from the latest scene.
        public string LatestSceneDate;
    }

    // Talks to the real satellite archive (Microsoft Planetary Computer, public, no key):
    // 1. STAC search by the exact scene IDs the analysis used -> how many the archive confirms.
    // 2. Data API render of the latest scene, cropped to the model area -> preview image.
    // The analysis itself is precomputed (district.json); this verifies and shows its inputs.
    public static class ArchiveSync
    {
        const string StacSearch = "https://planetarycomputer.microsoft.com/api/stac/v1/search";
        const string DataBbox = "https://planetarycomputer.microsoft.com/api/data/v1/item/bbox/";
        const int TimeoutSeconds = 12;
        const int PageSize = 100;

        [Serializable] class SearchResponse { public Feature[] features; }
        [Serializable] class Feature { public string id; }
        [Serializable] class SearchBody { public string[] collections; public string[] ids; public int limit; }

        public static IEnumerator Run(SourceSync sync, float[] bbox, string cityKey = "cairo")
        {
            var src = sync.Source;
            sync.State = SyncState.Querying;
            if (!string.IsNullOrEmpty(src.itemUrl))
            {
                yield return VerifyItem(sync);
                yield break;
            }
            int found = 0;
            for (int start = 0; start < src.sceneIds.Length; start += PageSize)
            {
                var body = new SearchBody
                {
                    collections = new[] { src.collection },
                    ids = src.sceneIds.Skip(start).Take(PageSize).ToArray(),
                    limit = PageSize,
                };
                using var req = new UnityWebRequest(StacSearch, "POST")
                {
                    uploadHandler = new UploadHandlerRaw(System.Text.Encoding.UTF8.GetBytes(JsonUtility.ToJson(body))),
                    downloadHandler = new DownloadHandlerBuffer(),
                    timeout = TimeoutSeconds,
                };
                req.SetRequestHeader("Content-Type", "application/json");
                yield return req.SendWebRequest();
                if (req.result != UnityWebRequest.Result.Success)
                {
                    Debug.LogWarning($"{src.satellite}: archive query failed ({req.error}); using prepared data.");
                    sync.State = SyncState.Offline;
                    yield break;
                }
                found += JsonUtility.FromJson<SearchResponse>(req.downloadHandler.text).features?.Length ?? 0;
            }
            sync.Found = found;

            string latest = src.sceneIds[src.sceneIds.Length - 1];
            sync.LatestSceneDate = src.lastDate;
            // The preview image ships with the app (same render, analysis/report/app_images.py):
            // the scene list is still checked live above, but no slow image render is awaited.
            string slug = System.Text.RegularExpressions.Regex.Replace(src.satellite.ToLowerInvariant(), "[^a-z0-9]+", "_").Trim('_');
            var bundled = Resources.Load<Texture2D>($"Districts/{cityKey}/preview_{slug}");
            if (bundled != null)
            {
                sync.Preview = bundled;
                sync.State = SyncState.Complete;
                Debug.Log($"{src.satellite}: archive confirmed {found}/{src.sceneIds.Length} scenes; preview shipped with the app.");
                yield break;
            }
            sync.State = SyncState.Downloading;
            string box = string.Join(",", bbox.Select(v => v.ToString(CultureInfo.InvariantCulture)));
            string url = $"{DataBbox}{box}/256x256.png?collection={src.collection}&item={latest}&{src.previewQuery}";
            using (var img = UnityWebRequestTexture.GetTexture(url))
            {
                img.timeout = TimeoutSeconds;
                yield return img.SendWebRequest();
                if (img.result == UnityWebRequest.Result.Success)
                    sync.Preview = DownloadHandlerTexture.GetContent(img);
                else
                    Debug.LogWarning($"{src.satellite}: preview download failed ({img.error}).");
            }
            sync.State = SyncState.Complete;
            Debug.Log($"{src.satellite}: archive confirmed {found}/{src.sceneIds.Length} scenes; " +
                      $"preview {(sync.Preview != null ? $"{sync.Preview.width}x{sync.Preview.height}" : "unavailable")}.");
        }

        // Catalogues whose search ignores id filters (DLR): fetch the item itself. Metadata is
        // public; the data needs a login, so no preview image is downloaded.
        static IEnumerator VerifyItem(SourceSync sync)
        {
            var src = sync.Source;
            using var req = UnityWebRequest.Get(src.itemUrl);
            req.timeout = TimeoutSeconds;
            yield return req.SendWebRequest();
            if (req.result != UnityWebRequest.Result.Success)
            {
                Debug.LogWarning($"{src.satellite}: archive query failed ({req.error}); using prepared data.");
                sync.State = SyncState.Offline;
                yield break;
            }
            sync.Found = src.sceneIds.Length;
            sync.LatestSceneDate = src.lastDate;
            sync.State = SyncState.Complete;
            Debug.Log($"{src.satellite}: archive confirmed {sync.Found}/{src.sceneIds.Length} scenes (metadata only).");
        }
    }
}
