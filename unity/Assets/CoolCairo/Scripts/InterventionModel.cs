using System;

namespace CoolCairo
{
    public enum Intervention { CoolRoof, Trees }

    // C# port of analysis/src/coolcairo/interventions.py. Keep the two in sync.
    // Pure arithmetic on precomputed regression coefficients: no model solving at runtime.
    // All temperatures are land SURFACE temperature (Landsat LST), not air temperature.
    public class InterventionModel
    {
        // Street trees can cover at most this share of a block's dark ground (matches the report).
        public const float MaxTreeShareOfDarkGround = 0.25f;

        readonly DistrictData _d;
        readonly float[] _coolRoofShare;  // 0..1 of the block's roofs (dark and pale) coated.
        readonly float[] _treeShare;      // 0..1 of the plantable dark ground planted.

        public event Action Changed;

        public InterventionModel(DistrictData district)
        {
            _d = district;
            _coolRoofShare = new float[district.BlockCount];
            _treeShare = new float[district.BlockCount];
        }

        public bool IsValid(int block) => _d.blocks.valid[block] == 1;

        public float BaselineLst(int block) => _d.blocks.lstC[block];

        // Delta LST (deg C, negative = cooler) for one block with its current interventions.
        public float DeltaLst(int block)
        {
            if (!IsValid(block)) return 0f;
            var b = _d.blocks;
            var m = _d.model;
            float coated = _coolRoofShare[block];
            float roof = coated * (m.coolRoofDarkDeltaC * b.darkRoofFrac[block]
                                   + m.coolRoofPaleDeltaC * b.paleRoofFrac[block]);
            float groundPlanted = _treeShare[block] * MaxTreeShareOfDarkGround * b.darkGroundFrac[block];
            return roof + (m.vegFrac - m.darkGroundFrac) * groundPlanted;
        }

        public float Lst(int block) => BaselineLst(block) + DeltaLst(block);

        // Dark-roof share of the uncoated roof area, for colouring roofs.
        public float DarkRoofShareOfRoofs(int block)
        {
            var b = _d.blocks;
            if (b.roofFrac[block] <= 0f) return 0f;
            return b.darkRoofFrac[block] / b.roofFrac[block];
        }

        public void Apply(Intervention kind, int block, float amount)
        {
            if (block < 0 || !IsValid(block)) return;
            var arr = kind == Intervention.CoolRoof ? _coolRoofShare : _treeShare;
            float next = Math.Clamp(arr[block] + amount, 0f, 1f);
            if (next == arr[block]) return;
            arr[block] = next;
            Changed?.Invoke();
        }

        public void ResetAll()
        {
            Array.Clear(_coolRoofShare, 0, _coolRoofShare.Length);
            Array.Clear(_treeShare, 0, _treeShare.Length);
            Changed?.Invoke();
        }

        public float Share(Intervention kind, int block) =>
            kind == Intervention.CoolRoof ? _coolRoofShare[block] : _treeShare[block];

        // District mean surface temperature over valid blocks, before or after interventions.
        public float MeanLst(bool withInterventions = true)
        {
            float sum = 0f;
            int n = 0;
            for (int i = 0; i < _d.BlockCount; i++)
            {
                if (!IsValid(i)) continue;
                sum += withInterventions ? Lst(i) : BaselineLst(i);
                n++;
            }
            return n == 0 ? 0f : sum / n;
        }

        // District mean delta LST over valid blocks.
        public float MeanDelta()
        {
            float sum = 0f;
            int n = 0;
            for (int i = 0; i < _d.BlockCount; i++)
            {
                if (!IsValid(i)) continue;
                sum += DeltaLst(i);
                n++;
            }
            return n == 0 ? 0f : sum / n;
        }

        // Heat exposure (heat risk): residents x degrees above the reference surface temperature.
        // Mirrors coolcairo.population.heat_exposure.
        public float Residents(int block) => IsValid(block) ? Math.Max(0f, _d.blocks.population[block]) : 0f;

        public float Exposure(int block, bool withInterventions = true)
        {
            if (!IsValid(block)) return 0f;
            float lst = withInterventions ? Lst(block) : BaselineLst(block);
            return Residents(block) * Math.Max(0f, lst - _d.model.heatReferenceC);
        }

        public float TotalExposure(bool withInterventions = true)
        {
            float sum = 0f;
            for (int i = 0; i < _d.BlockCount; i++) sum += Exposure(i, withInterventions);
            return sum;
        }

        public float TotalResidents()
        {
            float sum = 0f;
            for (int i = 0; i < _d.BlockCount; i++) sum += Residents(i);
            return sum;
        }

        // Residents living in blocks whose surface temperature the interventions lowered.
        public float ResidentsInCooledBlocks()
        {
            float sum = 0f;
            for (int i = 0; i < _d.BlockCount; i++)
                if (DeltaLst(i) < -0.01f) sum += Residents(i);
            return sum;
        }
    }
}
