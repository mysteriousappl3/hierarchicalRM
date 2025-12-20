using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;

namespace Obi
{
    public class ComputeClothRenderSystem : ObiClothRenderSystem, RenderSystem<ObiClothRenderer>
    {
        public Oni.RenderingSystemType typeEnum { get => Oni.RenderingSystemType.Cloth; }

        public RendererSet<ObiClothRenderer> renderers { get; } = new RendererSet<ObiClothRenderer>();

        protected override IReadOnlyList<ObiClothRendererBase> baseRenderers { get { return renderers.AsReadOnly(); } }

        private ComputeShader clothShader;
        private int updateClothKernel;

        public ComputeClothRenderSystem(ObiSolver solver) : base(solver)
        {
            clothShader = GameObject.Instantiate(Resources.Load<ComputeShader>("Compute/ClothRendering"));
            updateClothKernel = clothShader.FindKernel("UpdateClothMesh");
        }

        protected override void CloseBatches()
        {
            for (int i = 0; i < batchList.Count; ++i)
                batchList[i].Initialize(sortedRenderers, meshData, meshIndices, layout, true);

            skinmapData.PrepareForCompute();
            meshData.PrepareForCompute();

            skinMapIndices.AsComputeBuffer<int>();
            meshIndices.AsComputeBuffer<int>();

            particleOffsets.AsComputeBuffer<int>();
            vertexOffsets.AsComputeBuffer<int>();

            base.CloseBatches();
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

