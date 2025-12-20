#if (OBI_BURST && OBI_MATHEMATICS && OBI_COLLECTIONS)
using Unity.Jobs;
using Unity.Collections;
using Unity.Mathematics;
using Unity.Burst;
using UnityEngine;
using UnityEngine.Rendering;
using System.Collections.Generic;

namespace Obi
{
    public class BurstSkinnedClothRenderSystem : ObiSkinnedClothRenderSystem, RenderSystem<ObiSkinnedClothRenderer>
    {
        public Oni.RenderingSystemType typeEnum { get => Oni.RenderingSystemType.SkinnedCloth; }

        public RendererSet<ObiSkinnedClothRenderer> renderers { get; } = new RendererSet<ObiSkinnedClothRenderer>();

        protected override IReadOnlyList<ObiClothRendererBase> baseRenderers { get { return renderers.AsReadOnly(); } }

        public BurstSkinnedClothRenderSystem(ObiSolver solver) : base(solver)
        {
        }

        protected override void CloseBatches()
        {
            for (int i = 0; i < batchList.Count; ++i)
                batchList[i].Initialize(sortedRenderers, meshData, meshIndices, layout, false);

            // dispose of uv/triangle information since we're not using it anymore.
            meshData.DisposeOfStaticData();

            base.CloseBatches();
        }

        public override void Step() 
        {
            // We don't add/remove skin constraints between the solver's interpolation and simulation callbacks, so it's fine to assume
            // the constraints we work with here are the same that existed during the last SetupRender().

            var solverSkinConstraints = m_Solver.GetConstraintsByType(Oni.ConstraintType.Skin) as ObiConstraints<ObiSkinConstraintsBatch>;

            if (solverSkinConstraints != null && solverSkinConstraints.batchCount > 0)
            {
                // there's a single skin constraints batch, guaranteed.
                var solverBatch = solverSkinConstraints.batches[0] as ObiSkinConstraintsBatch;

                UpdateBoneTransformData();

                for (int i = 0; i < batchList.Count; ++i)
                {
                    var batch = batchList[i];

                    // update meshes:
                    var updateJob = new UpdateSkinJob
                    {
                        rendererIndices = batch.particleToRenderer.AsNativeArray<int>(),
                        skinmapIndices = skinMapIndices.AsNativeArray<int>(),
                        skeletonIndices = skeletonIndices.AsNativeArray<int>(),

                        skinConstraintOffsets = skinConstraintBatchOffsets.AsNativeArray<int>(),
                        particleOffsets = particleOffsets.AsNativeArray<int>(),
                        influenceOffsets = skinmapData.skinWeightOffsets.AsNativeArray<int>(),

                        particleIndices = batch.particleIndices.AsNativeArray<int>(),

                        restPositions = m_Solver.restPositions.AsNativeArray<float4>(),
                        restOrientations = m_Solver.restOrientations.AsNativeArray<quaternion>(),

                        skinData = skinmapData.skinData.AsNativeArray<SkinmapDataBatch.SkinmapData>(),
                        skeletonData = skeletonData.skeletonData.AsNativeArray<SkeletonDataBatch.SkeletonData>(),

                        boneBindMatrices = skinmapData.boneBindPoses.AsNativeArray<float4x4>(),
                        skinWeights = skinmapData.skinWeights.AsNativeArray<ObiInfluenceMap.Influence>(),

                        bonePos = skeletonData.bonePositions.AsNativeArray<float3>(),
                        boneRot = skeletonData.boneRotations.AsNativeArray<quaternion>(),
                        boneScl = skeletonData.boneScales.AsNativeArray<float3>(),

                        skinConstraintPoints = solverBatch.skinPoints.AsNativeArray<float4>(),
                        skinConstraintNormals = solverBatch.skinNormals.AsNativeArray<float4>(),

                        world2Solver = m_Solver.transform.worldToLocalMatrix
                    };

                    updateJob.Schedule(batch.particleCount, 16).Complete();
                }
            }
        }

        public void Render()
        {
            if (!Application.isPlaying)
                return;

            using (m_RenderMarker.Auto())
            {

                for (int i = 0; i < batchList.Count; ++i)
                {
                    var batch = batchList[i];

                    // update meshes:
                    var updateJob = new UpdateClothMeshJob
                    {
                        rendererIndices = batch.vertexToRenderer.AsNativeArray<int>(),
                        skinmapIndices = skinMapIndices.AsNativeArray<int>(),
                        meshIndices = meshIndices.AsNativeArray<int>(),

                        vertexOffsets = vertexOffsets.AsNativeArray<int>(),
                        particleOffsets = particleOffsets.AsNativeArray<int>(),
                        influenceOffsets = skinmapData.influenceOffsets.AsNativeArray<int>(),

                        particleIndices = batch.particleIndices.AsNativeArray<int>(),

                        renderablePositions = m_Solver.renderablePositions.AsNativeArray<float4>(),
                        renderableOrientations = m_Solver.renderableOrientations.AsNativeArray<quaternion>(),
                        colors = m_Solver.colors.AsNativeArray<float4>(),

                        skinData = skinmapData.skinData.AsNativeArray<SkinmapDataBatch.SkinmapData>(),
                        meshData = meshData.meshData.AsNativeArray<MeshDataBatch.MeshData>(),

                        particleBindMatrices = skinmapData.particleBindPoses.AsNativeArray<float4x4>(),
                        influences = skinmapData.influences.AsNativeArray<ObiInfluenceMap.Influence>(),

                        positions = meshData.restPositions.AsNativeArray<float3>(),
                        normals = meshData.restNormals.AsNativeArray<float3>(),
                        tangents = meshData.restTangents.AsNativeArray<float4>(),

                        vertices = batch.dynamicVertexData.AsNativeArray<DynamicBatchVertex>(),
                    };

                    updateJob.Schedule(batch.vertexCount, 16).Complete();

                    batch.mesh.SetVertexBufferData(batch.dynamicVertexData.AsNativeArray<DynamicBatchVertex>(), 0, 0, batch.vertexCount, 0, MeshUpdateFlags.DontValidateIndices | MeshUpdateFlags.DontRecalculateBounds | MeshUpdateFlags.DontResetBoneBounds | MeshUpdateFlags.DontNotifyMeshUsers);

                    var rp = batch.renderParams;
                    rp.worldBounds = m_Solver.bounds;

                    for (int m = 0; m < batch.materials.Length; ++m)
                    {
                        rp.material = batch.materials[m];
                        Graphics.RenderMesh(rp, batch.mesh, m, m_Solver.transform.localToWorldMatrix, null);
                    }
                }
            }
        }
    }
}
#endif

