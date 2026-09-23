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
        public float[] darkGroundFrac;
        public float[] roofFrac;
        public float[] meanHeightM;
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
    public class ModelCoefficients
    {
        public float intercept;
        public float vegFrac;
        public float darkRoofFrac;
        public float darkGroundFrac;
        public float roofFrac;
        public float meanHeightM;
        public float r2SpatialCv;
        public float maeSpatialCv;
        public int nBlocks;
    }
}
