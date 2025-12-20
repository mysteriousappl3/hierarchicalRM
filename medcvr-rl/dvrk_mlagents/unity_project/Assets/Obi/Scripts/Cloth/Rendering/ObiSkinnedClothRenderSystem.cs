using UnityEngine;

namespace Obi
{
   
    public abstract class ObiSkinnedClothRenderSystem : ObiClothRenderSystem
    {

        protected SkeletonDataBatch skeletonData;
        protected ObiNativeList<int> skeletonIndices; // for each renderer, its skeleton index.
        protected ObiNativeList<int> skinConstraintBatchOffsets; // for each renderer, its offset in the skin constraints batch.


        public ObiSkinnedClothRenderSystem(ObiSolver solver) : base(solver)
        {
            m_Solver = solver;

            skeletonData = new SkeletonDataBatch();

            skeletonIndices = new ObiNativeList<int>();
            skinConstraintBatchOffsets = new ObiNativeList<int>();
        }

        public override void Dispose()
        {
            base.Dispose();

            skeletonData.Dispose();

            if (skeletonIndices != null)
                skeletonIndices.Dispose();
            if (skinConstraintBatchOffsets != null)
                skinConstraintBatchOffsets.Dispose();
        }

        protected override void Clear()
        {
            base.Clear();

            skeletonData.Clear();
            skinConstraintBatchOffsets.Clear();

            skeletonIndices.Clear();
            skinConstraintBatchOffsets.Clear();
        }

        protected override void PopulateBatches()
        {
            // store per-mesh data 
            for (int i = 0; i < sortedRenderers.Count; ++i)
            {
                // add skinmap index:
                skinMapIndices.Add(skinmapData.AddSkinmap(sortedRenderers[i].skinMap, sortedRenderers[i].sourceMesh.bindposes));

                // add mesh index
                meshIndices.Add(meshData.AddMesh(sortedRenderers[i]));

                // add skeleton index:
                var skRenderer = sortedRenderers[i].GetComponent<SkinnedMeshRenderer>();
                skeletonIndices.Add(skeletonData.AddSkeleton(skRenderer.bones, sortedRenderers[i].actor.solver.transform.worldToLocalMatrix));

                // add offset in skin constraints:
                skinConstraintBatchOffsets.Add(-1);
            }
        }

        protected void UpdateBoneTransformData()
        {
            // iterate over all renderers, copying bone transform data to bone arrays:
            int k = 0;
            for (int i = 0; i < sortedRenderers.Count; ++i)
            {
                var renderer = sortedRenderers[i] as ObiSkinnedClothRenderer;

                // update skin batch offset:
                skinConstraintBatchOffsets[i] = sortedRenderers[i].actor.solverBatchOffsets[(int)Oni.ConstraintType.Skin][0];

                skeletonData.SetWorldToSolverTransform(k, renderer.actor.solver.transform.worldToLocalMatrix);

                var bones = renderer.GetComponent<SkinnedMeshRenderer>().bones;
                for (int j = 0; j < bones.Length; ++j)
                    skeletonData.SetBoneTransform(k, j, bones[j]);
                
                k++;
            }
        }
    }
}

