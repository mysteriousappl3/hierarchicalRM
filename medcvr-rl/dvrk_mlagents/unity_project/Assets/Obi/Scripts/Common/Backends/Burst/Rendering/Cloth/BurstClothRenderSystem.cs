#if (OBI_BURST && OBI_MATHEMATICS && OBI_COLLECTIONS)
using Unity.Jobs;
using Unity.Collections;
using Unity.Mathematics;
using Unity.Burst;
using UnityEngine;
using System.Runtime.InteropServices;
using UnityEngine.Rendering;
using System.Collections.Generic;

namespace Obi
{
    public class BurstClothRenderSystem : ObiClothRenderSystem, RenderSystem<ObiClothRenderer>
    {
        public Oni.RenderingSystemType typeEnum { get => Oni.RenderingSystemType.Cloth; }

        public RendererSet<ObiClothRenderer> renderers { get; } = new RendererSet<ObiClothRenderer>();

        protected override IReadOnlyList<ObiClothRendererBase> baseRenderers { get { return renderers.AsReadOnly(); } }

        public BurstClothRenderSystem(ObiSolver solver) : base(solver)
        {
        }

        protected override void CloseBatches()
        {
            for (int i = 0; i < batchList.Count; ++i)
                batchList[i].Initialize(sortedRenderers, meshData, meshIndices, layout, false);

            base.CloseBatches();
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
                        Graphics.RenderMesh(rp, batch.mesh, m, m_Solver.transform.localToWorldMatrix);
                    }
                }
            }
        }

        
    }
}
#endif

