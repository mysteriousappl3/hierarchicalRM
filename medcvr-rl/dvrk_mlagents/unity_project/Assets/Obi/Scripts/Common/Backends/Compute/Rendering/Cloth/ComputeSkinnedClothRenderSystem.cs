using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;

namespace Obi
{
    public class ComputeSkinnedClothRenderSystem : ObiSkinnedClothRenderSystem, RenderSystem<ObiSkinnedClothRenderer>
    {
        public Oni.RenderingSystemType typeEnum { get => Oni.RenderingSystemType.SkinnedCloth; }

        public RendererSet<ObiSkinnedClothRenderer> renderers { get; } = new RendererSet<ObiSkinnedClothRenderer>();

        protected override IReadOnlyList<ObiClothRendererBase> baseRenderers { get { return renderers.AsReadOnly(); } }

        private ComputeShader clothShader;
        private int skinUpdateKernel;
        private int updateClothKernel;

        public ComputeSkinnedClothRenderSystem(ObiSolver solver) : base(solver)
        {
            clothShader = GameObject.Instantiate(Resources.Load<ComputeShader>("Compute/ClothRendering"));
            skinUpdateKernel = clothShader.FindKernel("UpdateSkinConstraints");
            updateClothKernel = clothShader.FindKernel("UpdateClothMesh");
        }

        protected override void CloseBatches()
        {
            for (int i = 0; i < batchList.Count; ++i)
                batchList[i].Initialize(sortedRenderers, meshData, meshIndices, layout, true);

            // dispose of uv/triangle information since we're not using it anymore.
            meshData.DisposeOfStaticData();

            skinmapData.PrepareForCompute();
            meshData.PrepareForCompute();
            skeletonData.PrepareForCompute();

            skinMapIndices.AsComputeBuffer<int>();
            meshIndices.AsComputeBuffer<int>();
            skeletonIndices.SafeAsComputeBuffer<int>();

            skinConstraintBatchOffsets.SafeAsComputeBuffer<int>();

            particleOffsets.AsComputeBuffer<int>();
            vertexOffsets.AsComputeBuffer<int>();
        }

        public override void Step()
        {
            var solverSkinConstraints = m_Solver.GetConstraintsByType(Oni.ConstraintType.Skin) as ObiConstraints<ObiSkinConstraintsBatch>;

            // guard against skinmapIndices being null, since Step() is called by the solver before setting up render structures.
            if (skinMapIndices.computeBuffer != null && solverSkinConstraints != null && solverSkinConstraints.batchCount > 0)
            {
                // there's a single skin constraints batch, guaranteed.
                var solverBatch = solverSkinConstraints.batches[0] as ObiSkinConstraintsBatch;

                UpdateBoneTransformData();
                skinConstraintBatchOffsets.Upload();

                skeletonData.UpdateBoneTransformsCompute();

                var computeSolver = m_Solver.implementation as ComputeSolverImpl;

                if (skinMapIndices.computeBuffer == null)
                    Debug.Log("NULL");
                clothShader.SetBuffer(skinUpdateKernel, "skinmapIndices", skinMapIndices.computeBuffer);
                clothShader.SetBuffer(skinUpdateKernel, "skeletonIndices", skeletonIndices.computeBuffer);
                clothShader.SetBuffer(skinUpdateKernel, "particleOffsets", particleOffsets.computeBuffer);

                clothShader.SetBuffer(skinUpdateKernel, "skinConstraintOffsets", skinConstraintBatchOffsets.computeBuffer);

                clothShader.SetBuffer(skinUpdateKernel, "skinData", skinmapData.skinData.computeBuffer);
                clothShader.SetBuffer(skinUpdateKernel, "influences", skinmapData.skinWeights.computeBuffer);
                clothShader.SetBuffer(skinUpdateKernel, "influenceOffsets", skinmapData.skinWeightOffsets.computeBuffer);
                clothShader.SetBuffer(skinUpdateKernel, "boneBindMatrices", skinmapData.boneBindPoses.computeBuffer);

                clothShader.SetBuffer(skinUpdateKernel, "skeletonData", skeletonData.skeletonData.computeBuffer);
                clothShader.SetBuffer(skinUpdateKernel, "bonePos", skeletonData.bonePositions.computeBuffer);
                clothShader.SetBuffer(skinUpdateKernel, "boneRot", skeletonData.boneRotations.computeBuffer);
                clothShader.SetBuffer(skinUpdateKernel, "boneScl", skeletonData.boneScales.computeBuffer);

                clothShader.SetBuffer(skinUpdateKernel, "restPositions", computeSolver.restPositionsBuffer);
                clothShader.SetBuffer(skinUpdateKernel, "restOrientations", computeSolver.restOrientationsBuffer);

                clothShader.SetBuffer(skinUpdateKernel, "skinConstraintPoints", solverBatch.skinPoints.computeBuffer);
                clothShader.SetBuffer(skinUpdateKernel, "skinConstraintNormals", solverBatch.skinNormals.computeBuffer);

                clothShader.SetMatrix("world2Solver", m_Solver.transform.worldToLocalMatrix);

                for (int i = 0; i < batchList.Count; ++i)
                {
                    var batch = batchList[i];
                    int threadGroups = ComputeMath.ThreadGroupCount(batch.particleCount, 128);

                    clothShader.SetInt("constraintCount", batch.particleCount);

                    clothShader.SetBuffer(skinUpdateKernel, "rendererIndices", batch.particleToRenderer.computeBuffer);
                    clothShader.SetBuffer(skinUpdateKernel, "particleIndices", batch.particleIndices.computeBuffer);

                    clothShader.Dispatch(skinUpdateKernel, threadGroups, 1, 1);
                }
            }
        }

        public void Render()
        {
            // Don't render the meshes in-editor.
            if (!Application.isPlaying)
                return;

            using (m_RenderMarker.Auto())
            {
                var computeSolver = m_Solver.implementation as ComputeSolverImpl;

                if (computeSolver.renderablePositionsBuffer != null && computeSolver.renderablePositionsBuffer.count > 0)
                {
                    clothShader.SetBuffer(updateClothKernel, "skinmapIndices", skinMapIndices.computeBuffer);
                    clothShader.SetBuffer(updateClothKernel, "meshIndices", meshIndices.computeBuffer);
                    clothShader.SetBuffer(updateClothKernel, "particleOffsets", particleOffsets.computeBuffer);
                    clothShader.SetBuffer(updateClothKernel, "vertexOffsets", vertexOffsets.computeBuffer);

                    clothShader.SetBuffer(updateClothKernel, "skinData", skinmapData.skinData.computeBuffer);
                    clothShader.SetBuffer(updateClothKernel, "influences", skinmapData.influences.computeBuffer);
                    clothShader.SetBuffer(updateClothKernel, "influenceOffsets", skinmapData.influenceOffsets.computeBuffer);
                    clothShader.SetBuffer(updateClothKernel, "particleBindMatrices", skinmapData.particleBindPoses.computeBuffer);

                    clothShader.SetBuffer(updateClothKernel, "meshData", meshData.meshData.computeBuffer);
                    clothShader.SetBuffer(updateClothKernel, "positions", meshData.restPositions.computeBuffer);
                    clothShader.SetBuffer(updateClothKernel, "normals", meshData.restNormals.computeBuffer);
                    clothShader.SetBuffer(updateClothKernel, "tangents", meshData.restTangents.computeBuffer);

                    clothShader.SetBuffer(updateClothKernel, "renderablePositions", computeSolver.renderablePositionsBuffer);
                    clothShader.SetBuffer(updateClothKernel, "renderableOrientations", computeSolver.renderableOrientationsBuffer);
                    clothShader.SetBuffer(updateClothKernel, "colors", computeSolver.colorsBuffer);

                    for (int i = 0; i < batchList.Count; ++i)
                    {
                        var batch = batchList[i];
                        int threadGroups = ComputeMath.ThreadGroupCount(batch.vertexCount, 128);

                        clothShader.SetInt("vertexCount", batch.vertexCount);

                        clothShader.SetBuffer(updateClothKernel, "rendererIndices", batch.vertexToRenderer.computeBuffer);
                        clothShader.SetBuffer(updateClothKernel, "particleIndices", batch.particleIndices.computeBuffer);

                        clothShader.SetBuffer(updateClothKernel, "vertices", batch.gpuVertexBuffer);

                        clothShader.Dispatch(updateClothKernel, threadGroups, 1, 1);

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
}

