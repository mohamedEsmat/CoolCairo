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
        // Heat exposure = residents x max(0, LST - heatReferenceC), in person-degrees.
        public float heatReferenceC;
    }
}
