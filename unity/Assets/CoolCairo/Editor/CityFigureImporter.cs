using UnityEditor;

namespace CoolCairo.EditorTools
{
    // The analysis maps of the cities beyond Cairo (Resources/Districts/<key>/*.png, drawn by
    // analysis/report/city_figures.py) are imported like Cairo's: sharp, unscaled UI images with
    // no mipmaps or compression blur, full size up to 2048 px.
    public class CityFigureImporter : AssetPostprocessor
    {
        void OnPreprocessTexture()
        {
            if (!assetPath.Replace('\\', '/').Contains("/Resources/Districts/")) return;
            var importer = (TextureImporter)assetImporter;
            importer.textureType = TextureImporterType.Default;
            importer.mipmapEnabled = false;
            importer.wrapMode = UnityEngine.TextureWrapMode.Clamp;
            importer.maxTextureSize = 2048;
            importer.textureCompression = TextureImporterCompression.Uncompressed;
        }
    }
}
