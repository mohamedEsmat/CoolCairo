using System;
using UnityEngine;

namespace CoolCairo
{
    // Mirrors export/district.json, written by analysis/src/coolcairo/export.py.
    // World origin = south-west corner of the block grid. +X = east, +Z = north, metres.
    // Block arrays are row-major with row 0 = south.

    [Serializable]
    public class DistrictData
    {
        public int schemaVersion;
        public string name;
        public string crs;
        public double originX;
        public double originY;
        public float blockSize;
        public int rows;
        public int cols;
        public BlockArrays blocks;
        public BuildingArrays buildings;
        public ModelCoefficients model;
        public SourceInfo[] sources;     // Satellite scenes the analysis used.
        public float[] previewBbox;      // [min_lon, min_lat, max_lon, max_lat] for archive previews.
        public HyperspectralInfo hyperspectral;
        public EnmapInfo enmap;          // EnMAP material fractions and their heat model (Cairo).
        public FlyInInfo flyIn;          // Sentinel-2 close-up for the globe fly-in.
        public GrowthInfo growth;        // Urban growth summary (Growth view).
        public string city;              // e.g. "Casablanca" (empty in older exports: Cairo)
        public HeightSources heightSources;   // where the buildings' heights come from

        public string CityName => string.IsNullOrEmpty(city) ? "Cairo" : city;
        public bool HasHeightSources => heightSources != null &&
            heightSources.osmHeight + heightSources.osmLevels + heightSources.openBuildings + heightSources.@default > 0.5f;

        // EnMAP fractions for every block and the heat model built on them (a confirmed library).
        public bool HasEnmap => enmap != null && enmap.available == 1 && blocks.enmapSand != null
                                && blocks.enmapSand.Length == BlockCount;

        public bool HasGrowth => growth != null && growth.available == 1
                                 && blocks.growthClass != null && blocks.growthClass.Length == BlockCount;

        public int BlockCount => rows * cols;

        public static DistrictData FromJson(string json)
        {
            var data = JsonUtility.FromJson<DistrictData>(json);
            if (data.schemaVersion != 1)
                throw new InvalidOperationException($"Unsupported district schema {data.schemaVersion}");
            return data;
        }

        public int BlockAt(Vector3 world)
        {
            int col = Mathf.FloorToInt(world.x / blockSize);
            int row = Mathf.FloorToInt(world.z / blockSize);
            if (col < 0 || col >= cols || row < 0 || row >= rows) return -1;
            return row * cols + col;
        }

        public Vector3 BlockCentre(int index) =>
            new Vector3((index % cols + 0.5f) * blockSize, 0f, (index / cols + 0.5f) * blockSize);
    }

    [Serializable]
    public class BlockArrays
    {
        public int[] valid;
        public float[] lstC;
        public float[] vegFrac;
        public float[] darkRoofFrac;
        public float[] paleRoofFrac;
        public float[] darkGroundFrac;
        public float[] soilFrac;
        public float[] roofFrac;
        public float[] meanHeightM;
        public float[] population;   // Residents per block (WorldPop 2024).
        // Building cover in the first / last growth year (Open Buildings Temporal) and the
        // Growth-view class: 0 still open, 1 built before, 2 built before and denser, 3 newly built.
        public float[] builtFirst;
        public float[] builtLast;
        public int[] growthClass;
        // EnMAP fractions per block (FCLS unmixing with the confirmed spectral library; they sum
        // to 1 with shade). Absent for cities without a library.
        public float[] enmapSand;
        public float[] enmapPaleRoof;
        public float[] enmapDustyRoof;
        public float[] enmapAsphalt;
        public float[] enmapVegetation;
        public float[] enmapShade;
    }

    // EnMAP material model (analysis enmap_materials.py): what the cooling measures do when the
    // block materials come from EnMAP, and the figures the analysis computed with it.
    [Serializable]
    public class EnmapInfo
    {
        public int available;
        public string sceneId;
        public string acquired;
        public int libraryPixels;
        public string library;
        // Heat model, same blocks and held-out 1 km tiles: Sentinel-2 shares vs EnMAP fractions.
        public float r2Sentinel2;
        public float maeSentinel2;
        public float r2Enmap;
        public float maeEnmap;
        // Broadband albedo measured from each library spectrum.
        public float albedoPaleRoof;
        public float albedoDustyRoof;
        public float albedoAsphalt;
        public float albedoSand;
        // Surface temperature change per unit block area treated.
        public float coolRoofPaleDeltaC;
        public float coolRoofDustyDeltaC;
        public float coolPavementDeltaC;
        public float treesDeltaC;
        public float pocketParkDeltaC;
        // Fitted coefficients vs sand (deg C per unit block fraction).
        public float coefPaleRoof;
        public float coefDustyRoof;
        public float coefAsphalt;
        public float coefVegetation;
        public float coefShade;
        public string attribution;
        // The analysis's own figures with this model (the self-test checks the app matches them).
        public float exposureBefore;
        public float pctCoolRoofs;
        public float pctStreetTrees;
        public float pctCoolPavements;
        public float pctPocketParks;
        public int targetedBlocks;
        public float targetedExposureAfter;
        public float targetedPct;
        public float targetedResidentsCooled;
    }

    [Serializable]
    public class GrowthInfo
    {
        public int available;
        public int firstYear;
        public int lastYear;
        public float builtFirstKm2;  // Building footprint area in the district, first year.
        public float builtLastKm2;
        public int newBlocks;
        public int denserBlocks;
        public float denserMin;      // Cover gain that makes a built-up block "denser".
        public string source;
    }

    // Shares of the district's buildings by height source (export.py _height_shares).
    [Serializable]
    public class HeightSources
    {
        public float osmHeight;      // OSM height tag
        public float osmLevels;      // OSM storeys x storey height
        public float openBuildings;  // Google Open Buildings 2.5D estimate
        public float @default;       // the config default (5 storeys): no height data
    }

    [Serializable]
    public class BuildingArrays
    {
        public int count;
        public int[] vertexStart;
        public int[] vertexCount;
        public float[] heightM;
        public int[] blockIndex;
        public float[] xz;
    }

    [Serializable]
    public class SourceInfo
    {
        public string satellite;     // e.g. "Landsat 9"
        public string collection;    // Planetary Computer STAC collection id
        public string use;           // What the analysis used it for
        public string[] sceneIds;
        public string firstDate;
        public string lastDate;
        public string previewQuery;  // Data API rendering parameters for the preview image
        public string itemUrl;       // If set, verify by fetching this STAC item (DLR / EnMAP)
    }

    [Serializable]
    public class FlyInInfo
    {
        public string collection;
        public string item;
        public string date;
        public float[] bbox;         // [min_lon, min_lat, max_lon, max_lat]
        public string query;         // Data API rendering parameters
    }

    // EnMAP result (analysis notebook 05): how much better hyperspectral spectra explain
    // block surface heat than Sentinel-2, with our model features, spatial CV.
    [Serializable]
    public class HyperspectralInfo
    {
        public int available;
        public string sceneId;
        public string acquired;
        public float r2Multispectral;
        public float r2Hyperspectral;
        // Spectra alone, same scene: EnMAP averaged into Sentinel-2's six bands vs the full spectrum.
        public float r2SpectraS2Bands;
        public float r2SpectraFull;
        public string attribution;   // Required by the EnMAP licence on every derived output.
    }

    [Serializable]
    public class ModelCoefficients
    {
        public float intercept;
        public float vegFrac;
        public float darkRoofFrac;
        public float darkGroundFrac;
        public float soilFrac;
        public float roofFrac;
        public float meanHeightM;
        public float r2SpatialCv;
        public float maeSpatialCv;
        public int nBlocks;
        // Surface temperature change per unit block area coated, by starting roof type.
        public float coolRoofDarkDeltaC;
        public float coolRoofPaleDeltaC;
        public string coolRoofMethod;
        // Per unit of block area converted (cool pavement: literature; pocket park: our model).
        public float coolPavementDeltaC;
        public float pocketParkDeltaC;
        // Adoption caps: share of a block's dark ground (trees) / bare sand (parks) convertible.
        public float treeMaxShare;
        public float parkMaxShare;
        // Heat exposure = residents x max(0, LST - heatReferenceC), in person-degrees.
        public float heatReferenceC;
    }
}
