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
        public FlyInInfo flyIn;          // Sentinel-2 close-up for the globe fly-in.
        public GrowthInfo growth;        // Urban growth summary (Growth view).

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
