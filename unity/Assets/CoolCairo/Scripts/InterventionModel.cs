using System;

namespace CoolCairo
{
    public enum Intervention { CoolRoof, Trees, CoolPavement, PocketPark }

    // C# port of analysis/src/coolcairo/interventions.py. Keep the two in sync.
    // Pure arithmetic on precomputed coefficients from district.json: no model solving at runtime.
    // All temperatures are land SURFACE temperature (Landsat LST), not air temperature.
    public class InterventionModel
    {
        readonly DistrictData _d;
        // Per intervention, per block: 0..1 of the intervention's full adoption in that block
        // (all roofs coated / cap of dark ground planted / remaining dark ground coated /
        // cap of bare sand greened).
        readonly float[][] _share;

        public event Action Changed;

        public InterventionModel(DistrictData district)
        {
            _d = district;
            int kinds = Enum.GetValues(typeof(Intervention)).Length;
            _share = new float[kinds][];
            for (int k = 0; k < kinds; k++) _share[k] = new float[district.BlockCount];
        }

        // Adoption caps exported from config (fallbacks for older district.json files).
        public float TreeMaxShare => _d.model.treeMaxShare > 0f ? _d.model.treeMaxShare : 0.25f;
        public float ParkMaxShare => _d.model.parkMaxShare > 0f ? _d.model.parkMaxShare : 0.5f;

        public bool IsValid(int block) => _d.blocks.valid[block] == 1;

        public float BaselineLst(int block) => _d.blocks.lstC[block];

        // Block-area shares changed by each intervention (used for the maths and for colouring).
        public float TreePlantedFrac(int block) =>
            Share(Intervention.Trees, block) * TreeMaxShare * _d.blocks.darkGroundFrac[block];

        // Pavements coat the dark ground that trees have not taken.
        public float PavementCoatedFrac(int block) =>
            Share(Intervention.CoolPavement, block) * (_d.blocks.darkGroundFrac[block] - TreePlantedFrac(block));

        public float ParkGreenedFrac(int block) =>
            Share(Intervention.PocketPark, block) * ParkMaxShare * _d.blocks.soilFrac[block];

        // Delta LST (deg C, negative = cooler) for one block with its current interventions.
        public float DeltaLst(int block)
        {
            if (!IsValid(block)) return 0f;
            var b = _d.blocks;
            var m = _d.model;
            float roof = Share(Intervention.CoolRoof, block)
                         * (m.coolRoofDarkDeltaC * b.darkRoofFrac[block] + m.coolRoofPaleDeltaC * b.paleRoofFrac[block]);
            float trees = (m.vegFrac - m.darkGroundFrac) * TreePlantedFrac(block);
            float pavement = m.coolPavementDeltaC * PavementCoatedFrac(block);
            float parks = m.pocketParkDeltaC * ParkGreenedFrac(block);
            return roof + trees + pavement + parks;
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
            var arr = _share[(int)kind];
            float next = Math.Clamp(arr[block] + amount, 0f, 1f);
            if (next == arr[block]) return;
            arr[block] = next;
            Changed?.Invoke();
        }

        public void ResetAll()
        {
            foreach (var arr in _share) Array.Clear(arr, 0, arr.Length);
            Changed?.Invoke();
        }

        public float Share(Intervention kind, int block) => _share[(int)kind][block];

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
