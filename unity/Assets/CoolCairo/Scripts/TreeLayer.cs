using System.Collections.Generic;
using UnityEngine;

namespace CoolCairo
{
    // Visual feedback for the tree intervention: instanced placeholder trees in planted blocks.
    // Positions are symbolic (the model is block-level): fixed pseudo-random spots per block,
    // outside building footprints. Replace the mesh with the designed tree model later.
    public class TreeLayer : MonoBehaviour
    {
        const int MaxTreesPerBlock = 14;
        const int BatchSize = 1023;
        const float CanopyDiameter = 6f;

        DistrictView _district;
        Mesh _mesh;
        RenderParams _params;
        List<Vector3>[] _spots;
        readonly List<Matrix4x4> _visible = new List<Matrix4x4>();
        readonly Matrix4x4[] _batch = new Matrix4x4[BatchSize];

        public void Init(DistrictView district, Material material)
        {
            _district = district;
            material.enableInstancing = true;
            _params = new RenderParams(material);
            _mesh = BuildTreeMesh();
            _spots = ComputeSpots(district.Data);
            district.Model.Changed += Rebuild;
            Rebuild();
        }

        void Rebuild()
        {
            _visible.Clear();
            var model = _district.Model;
            for (int block = 0; block < _spots.Length; block++)
            {
                // Street trees and pocket parks both show as trees in the block.
                float share = Mathf.Clamp01(model.Share(Intervention.Trees, block) + model.Share(Intervention.PocketPark, block));
                int n = Mathf.RoundToInt(share * _spots[block].Count);
                for (int i = 0; i < n; i++)
                {
                    var p = _spots[block][i];
                    float scale = 0.8f + 0.4f * Hash(block * 31 + i); // Stable size variation.
                    _visible.Add(Matrix4x4.TRS(p, Quaternion.Euler(0f, 360f * Hash(block + i * 7), 0f),
                                               Vector3.one * scale));
                }
            }
        }

        void Update()
        {
            for (int start = 0; start < _visible.Count; start += BatchSize)
            {
                int count = Mathf.Min(BatchSize, _visible.Count - start);
                _visible.CopyTo(start, _batch, 0, count);
                Graphics.RenderMeshInstanced(_params, _mesh, 0, _batch, count);
            }
        }

        static List<Vector3>[] ComputeSpots(DistrictData d)
        {
            // Buildings per block, so each candidate spot is only tested against nearby footprints.
            var byBlock = new List<int>[d.BlockCount];
            for (int i = 0; i < d.BlockCount; i++) byBlock[i] = new List<int>();
            for (int b = 0; b < d.buildings.count; b++) byBlock[d.buildings.blockIndex[b]].Add(b);

            var spots = new List<Vector3>[d.BlockCount];
            float margin = CanopyDiameter / 2f;
            for (int block = 0; block < d.BlockCount; block++)
            {
                spots[block] = new List<Vector3>();
                int row = block / d.cols, col = block % d.cols;
                for (int attempt = 0; attempt < MaxTreesPerBlock * 4 && spots[block].Count < MaxTreesPerBlock; attempt++)
                {
                    float x = (col + Hash(block * 97 + attempt * 2)) * d.blockSize;
                    float z = (row + Hash(block * 89 + attempt * 2 + 1)) * d.blockSize;
                    if (!InsideAnyNearbyBuilding(d, byBlock, row, col, x, z, margin))
                        spots[block].Add(new Vector3(x, 0f, z));
                }
            }
            return spots;
        }

        static bool InsideAnyNearbyBuilding(DistrictData d, List<int>[] byBlock, int row, int col,
                                            float x, float z, float margin)
        {
            // Footprints are assigned to blocks by centroid, so neighbours can overlap this block.
            for (int r = row - 1; r <= row + 1; r++)
            for (int c = col - 1; c <= col + 1; c++)
            {
                if (r < 0 || r >= d.rows || c < 0 || c >= d.cols) continue;
                foreach (int b in byBlock[r * d.cols + c])
                    if (PointInFootprint(d.buildings, b, x, z) ||
                        PointInFootprint(d.buildings, b, x + margin, z) ||
                        PointInFootprint(d.buildings, b, x - margin, z) ||
                        PointInFootprint(d.buildings, b, x, z + margin) ||
                        PointInFootprint(d.buildings, b, x, z - margin))
                        return true;
            }
            return false;
        }

        static bool PointInFootprint(BuildingArrays b, int building, float x, float z)
        {
            int start = b.vertexStart[building], n = b.vertexCount[building];
            bool inside = false;
            for (int i = 0, j = n - 1; i < n; j = i++)
            {
                float xi = b.xz[2 * (start + i)], zi = b.xz[2 * (start + i) + 1];
                float xj = b.xz[2 * (start + j)], zj = b.xz[2 * (start + j) + 1];
                if ((zi > z) != (zj > z) && x < (xj - xi) * (z - zi) / (zj - zi) + xi)
                    inside = !inside;
            }
            return inside;
        }

        // Deterministic 0..1 hash so trees stay put between repaints and sessions.
        static float Hash(int n)
        {
            unchecked
            {
                uint h = (uint)n * 747796405u + 2891336453u;
                h = ((h >> (int)((h >> 28) + 4u)) ^ h) * 277803737u;
                return ((h >> 22) ^ h) / (float)uint.MaxValue;
            }
        }

        static Mesh BuildTreeMesh()
        {
            // Trunk (brown cylinder) + canopy (green sphere), combined into one vertex-coloured mesh.
            var trunkGo = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
            var canopyGo = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            var trunk = trunkGo.GetComponent<MeshFilter>().sharedMesh;
            var canopy = canopyGo.GetComponent<MeshFilter>().sharedMesh;
            Destroy(trunkGo);
            Destroy(canopyGo);

            var mesh = new Mesh { name = "PlaceholderTree" };
            mesh.CombineMeshes(new[]
            {
                new CombineInstance
                {
                    mesh = trunk,
                    transform = Matrix4x4.TRS(new Vector3(0f, 1.5f, 0f), Quaternion.identity,
                                              new Vector3(0.5f, 1.5f, 0.5f)),
                },
                new CombineInstance
                {
                    mesh = canopy,
                    transform = Matrix4x4.TRS(new Vector3(0f, 5f, 0f), Quaternion.identity,
                                              new Vector3(CanopyDiameter, 4.5f, CanopyDiameter)),
                },
            }, true, true);

            var colors = new Color32[mesh.vertexCount];
            Color32 bark = new Color(0.40f, 0.29f, 0.20f), leaves = new Color(0.30f, 0.52f, 0.24f);
            for (int i = 0; i < colors.Length; i++) colors[i] = i < trunk.vertexCount ? bark : leaves;
            mesh.colors32 = colors;
            return mesh;
        }
    }
}
