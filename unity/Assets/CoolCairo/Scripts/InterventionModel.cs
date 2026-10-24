using System;
using System.Collections.Generic;
using System.Linq;

namespace CoolCairo
{
    public enum Intervention { CoolRoof, Trees, CoolPavement, PocketPark }

    // How the plan builder chooses blocks: most heat exposure, hottest surface or most residents
    // today (ties broken by surface temperature, as the report's targeted plan).
    // CoolingPotential: heat exposure the chosen measures can actually remove in the block, so a
    // plan skips hot blocks that have nothing to treat (no roofs, asphalt or sand mapped).
    public enum RankBy { HeatRisk, Temperature, Residents, CoolingPotential }

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

        // Undo: a copy of every share taken before each brush stroke and before Reset all.
        const int MaxUndo = 50;
        readonly List<float[][]> _undo = new List<float[][]>();

        // Counts changes, so a stroke that changed nothing can drop its undo step.
        public int Version { get; private set; }
        public bool CanUndo => _undo.Count > 0;

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
            return MeasureDelta(Intervention.CoolRoof, block) + MeasureDelta(Intervention.Trees, block)
                 + MeasureDelta(Intervention.CoolPavement, block) + MeasureDelta(Intervention.PocketPark, block);
        }

        // One measure's part of a block's Delta LST in the current plan (the parts add up).
        public float MeasureDelta(Intervention kind, int block) =>
            MeasureDeltaWith(kind, block, Share(Intervention.CoolRoof, block), Share(Intervention.Trees, block),
                             Share(Intervention.CoolPavement, block), Share(Intervention.PocketPark, block));

        // The same arithmetic for any shares (0..1 of each measure's full adoption in the block),
        // so the plan builder can preview a plan without applying it.
        float MeasureDeltaWith(Intervention kind, int block, float roof, float trees, float pavement, float park)
        {
            if (!IsValid(block)) return 0f;
            var b = _d.blocks;
            var m = _d.model;
            float planted = trees * TreeMaxShare * b.darkGroundFrac[block];
            return kind switch
            {
                Intervention.CoolRoof => roof * (m.coolRoofDarkDeltaC * b.darkRoofFrac[block] + m.coolRoofPaleDeltaC * b.paleRoofFrac[block]),
                Intervention.Trees => (m.vegFrac - m.darkGroundFrac) * planted,
                Intervention.CoolPavement => m.coolPavementDeltaC * pavement * (b.darkGroundFrac[block] - planted),
                _ => m.pocketParkDeltaC * park * ParkMaxShare * b.soilFrac[block],
            };
        }

        float DeltaWith(int block, float roof, float trees, float pavement, float park)
        {
            float sum = 0f;
            foreach (Intervention k in Enum.GetValues(typeof(Intervention)))
                sum += MeasureDeltaWith(k, block, roof, trees, pavement, park);
            return sum;
        }

        // ---------- plan builder ----------

        // Share of a block the four measures can change at all: roofs (cool roofs), dark ground
        // (street trees, then cool pavements on the rest) and the park cap of bare sand.
        public float TreatableShare(int block)
        {
            if (!IsValid(block)) return 0f;
            var b = _d.blocks;
            return b.roofFrac[block] + b.darkGroundFrac[block] + ParkMaxShare * b.soilFrac[block];
        }

        // Heat exposure these measures (at this adoption) would remove from one block, from today.
        public float RemovableExposure(int block, bool[] measures, float adoption)
        {
            if (!IsValid(block)) return 0f;
            float S(Intervention k) => measures != null && measures[(int)k] ? adoption : 0f;
            float delta = DeltaWith(block, S(Intervention.CoolRoof), S(Intervention.Trees), S(Intervention.CoolPavement), S(Intervention.PocketPark));
            float after = Residents(block) * Math.Max(0f, BaselineLst(block) + delta - _d.model.heatReferenceC);
            return Exposure(block, false) - after;
        }

        // Valid blocks in the builder's order (stable, as the report's targeted plan).
        public List<int> RankBlocks(RankBy by, bool[] measures = null, float adoption = 1f)
        {
            var valid = Enumerable.Range(0, _d.BlockCount).Where(IsValid);
            var ordered = by switch
            {
                RankBy.Temperature => valid.OrderByDescending(BaselineLst),
                RankBy.Residents => valid.OrderByDescending(Residents).ThenByDescending(BaselineLst),
                RankBy.CoolingPotential => valid.OrderByDescending(b => RemovableExposure(b, measures, adoption))
                                                .ThenByDescending(b => Exposure(b, false)).ThenByDescending(BaselineLst),
                _ => valid.OrderByDescending(b => Exposure(b, false)).ThenByDescending(BaselineLst),
            };
            return ordered.ToList();
        }

        // The blocks a plan covers: the first `share` of the ranking (1/3 of 576 = 192, as the report).
        public List<int> PlanBlocks(RankBy by, float share, bool[] measures = null, float adoption = 1f)
        {
            var ranked = RankBlocks(by, measures, adoption);
            int n = Math.Clamp((int)Math.Floor(ranked.Count * share + 1e-4f), 0, ranked.Count);
            return ranked.GetRange(0, n);
        }

        public struct PlanPreview { public float exposure, residentsCooled, residentsAboveTypical, meanLst; public int blocks; }

        // What a plan would do from today's district (nothing applied): the builder's preview.
        public PlanPreview Preview(bool[] measures, RankBy by, float share, float adoption)
        {
            var chosen = new HashSet<int>(PlanBlocks(by, share, measures, adoption));
            float S(Intervention k) => measures[(int)k] ? adoption : 0f;
            var p = new PlanPreview { blocks = chosen.Count };
            float lstSum = 0f;
            int n = 0;
            for (int i = 0; i < _d.BlockCount; i++)
            {
                if (!IsValid(i)) continue;
                float delta = chosen.Contains(i)
                    ? DeltaWith(i, S(Intervention.CoolRoof), S(Intervention.Trees), S(Intervention.CoolPavement), S(Intervention.PocketPark))
                    : 0f;
                float lst = BaselineLst(i) + delta;
                p.exposure += Residents(i) * Math.Max(0f, lst - _d.model.heatReferenceC);
                if (lst > _d.model.heatReferenceC) p.residentsAboveTypical += Residents(i);
                if (delta < -0.01f) p.residentsCooled += Residents(i);
                lstSum += lst;
                n++;
            }
            p.meanLst = n == 0 ? 0f : lstSum / n;
            return p;
        }

        // Replace the current plan with the builder's plan; one undo step.
        public void ApplyPlan(bool[] measures, RankBy by, float share, float adoption)
        {
            SaveUndo();
            var chosen = PlanBlocks(by, share, measures, adoption);
            Batch(() =>
            {
                foreach (var arr in _share) Array.Clear(arr, 0, arr.Length);
                Version++;
                foreach (int b in chosen)
                    for (int k = 0; k < _share.Length; k++)
                        if (measures[k]) Apply((Intervention)k, b, Math.Clamp(adoption, 0f, 1f));
            });
        }

        // Delta LST of one measure at full adoption in a block, on its own (no other measures):
        // coolcairo.interventions.full_adoption_deltas. Pavements then coat all the dark ground.
        public float FullAdoptionDelta(Intervention kind, int block)
        {
            if (!IsValid(block)) return 0f;
            var b = _d.blocks;
            var m = _d.model;
            return kind switch
            {
                Intervention.CoolRoof => m.coolRoofDarkDeltaC * b.darkRoofFrac[block] + m.coolRoofPaleDeltaC * b.paleRoofFrac[block],
                Intervention.Trees => (m.vegFrac - m.darkGroundFrac) * TreeMaxShare * b.darkGroundFrac[block],
                Intervention.CoolPavement => m.coolPavementDeltaC * b.darkGroundFrac[block],
                _ => m.pocketParkDeltaC * ParkMaxShare * b.soilFrac[block],
            };
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
            Version++;
            if (_batch == 0) Changed?.Invoke();
        }

        // Many changes as one: listeners hear about them once, at the end.
        int _batch;
        void Batch(Action changes)
        {
            int before = Version;
            _batch++;
            try { changes(); }
            finally { _batch--; }
            if (_batch == 0 && Version != before) Changed?.Invoke();
        }

        // The report's targeted plan: the riskiest third of valid blocks by today's heat exposure,
        // ties broken by surface temperature, hottest first (coolcairo.interventions.targeted_plan_delta).
        public List<int> TargetedPlanBlocks()
        {
            // Stable ordering, as AutoTest and DemoRecorder rank, so all three cool the same blocks.
            var ranked = Enumerable.Range(0, _d.BlockCount).Where(IsValid)
                .OrderByDescending(b => Exposure(b, false)).ThenByDescending(BaselineLst).ToList();
            return ranked.GetRange(0, ranked.Count / 3);
        }

        // Cool roofs + pocket parks on TargetedPlanBlocks, added to the current plan; one undo step.
        public void ApplyTargetedPlan()
        {
            SaveUndo();
            int before = Version;
            Batch(() =>
            {
                foreach (int b in TargetedPlanBlocks())
                {
                    Apply(Intervention.CoolRoof, b, 1f);
                    Apply(Intervention.PocketPark, b, 1f);
                }
            });
            if (Version == before) DropUndo();
        }

        // District heat exposure if one measure were applied in every block at full adoption,
        // on its own (coolcairo.interventions.exposure_reduction_summary).
        public float ExposureIfEverywhere(Intervention kind)
        {
            float sum = 0f;
            for (int i = 0; i < _d.BlockCount; i++)
            {
                if (!IsValid(i)) continue;
                sum += Residents(i) * Math.Max(0f, BaselineLst(i) + FullAdoptionDelta(kind, i) - _d.model.heatReferenceC);
            }
            return sum;
        }

        // Heat exposure the current plan removes, split by measure. In each block the removal is
        // shared out in proportion to each measure's part of the block's cooling, so the four
        // parts add up to the total removed.
        public float[] ExposureRemovedByMeasure()
        {
            var removed = new float[_share.Length];
            for (int i = 0; i < _d.BlockCount; i++)
            {
                float delta = DeltaLst(i);
                if (delta >= -1e-6f) continue;
                float gone = Exposure(i, false) - Exposure(i);
                if (gone <= 0f) continue;
                for (int k = 0; k < removed.Length; k++) removed[k] += gone * MeasureDelta((Intervention)k, i) / delta;
            }
            return removed;
        }

        // Blocks with any measure on them.
        public int TreatedBlocks()
        {
            int n = 0;
            for (int i = 0; i < _d.BlockCount; i++)
                foreach (var arr in _share)
                    if (arr[i] >= 0.01f) { n++; break; }
            return n;
        }

        // The blocks with the most heat exposure right now (with the plan), most first; only
        // blocks that still have some. Ties by surface temperature, as the targeted plan.
        public List<int> RiskiestBlocks(int count) =>
            Enumerable.Range(0, _d.BlockCount).Where(b => Exposure(b) > 0f)
                .OrderByDescending(b => Exposure(b)).ThenByDescending(Lst).Take(count).ToList();

        public void ResetAll()
        {
            if (HasPlan) SaveUndo();
            foreach (var arr in _share) Array.Clear(arr, 0, arr.Length);
            Version++;
            Changed?.Invoke();
        }

        // True when any block has any measure on it.
        public bool HasPlan
        {
            get
            {
                foreach (var arr in _share)
                    foreach (float v in arr)
                        if (v > 0f) return true;
                return false;
            }
        }

        public void SaveUndo()
        {
            var copy = new float[_share.Length][];
            for (int k = 0; k < _share.Length; k++) copy[k] = (float[])_share[k].Clone();
            _undo.Add(copy);
            if (_undo.Count > MaxUndo) _undo.RemoveAt(0);
        }

        // Forget the last undo step (a stroke that changed nothing).
        public void DropUndo()
        {
            if (_undo.Count > 0) _undo.RemoveAt(_undo.Count - 1);
        }

        // Back to the plan before the last stroke or Reset all.
        public bool Undo()
        {
            if (_undo.Count == 0) return false;
            var last = _undo[_undo.Count - 1];
            _undo.RemoveAt(_undo.Count - 1);
            for (int k = 0; k < _share.Length; k++) Array.Copy(last[k], _share[k], _share[k].Length);
            Version++;
            Changed?.Invoke();
            return true;
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

        // Residents living in blocks hotter than the typical block (the heat-exposure reference).
        public float ResidentsAboveTypical(bool withInterventions = true)
        {
            float sum = 0f;
            for (int i = 0; i < _d.BlockCount; i++)
            {
                if (!IsValid(i)) continue;
                float lst = withInterventions ? Lst(i) : BaselineLst(i);
                if (lst > _d.model.heatReferenceC) sum += Residents(i);
            }
            return sum;
        }

        // The blocks the plan treats (any measure on them, as TreatedBlocks): how many, their mean
        // surface temperature before and after, and the largest cooling of one block. A treated
        // block with nothing to change (no roofs, no sand) counts, at zero cooling.
        public (int blocks, float before, float after, float maxCooling) TreatedCooling()
        {
            int n = 0;
            float before = 0f, after = 0f, max = 0f;
            for (int i = 0; i < _d.BlockCount; i++)
            {
                if (!IsValid(i) || !_share.Any(arr => arr[i] >= 0.01f)) continue;
                float delta = DeltaLst(i);
                n++;
                before += BaselineLst(i);
                after += BaselineLst(i) + delta;
                max = Math.Min(max, delta);
            }
            return n == 0 ? (0, 0f, 0f, 0f) : (n, before / n, after / n, max);
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
