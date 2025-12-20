using System;
using UnityEngine;
using UnityEngine.Rendering;
using Unity.Profiling;
using System.Collections.Generic;

namespace Obi
{
    public abstract class ObiClothRenderSystem
    {
        protected abstract IReadOnlyList<ObiClothRendererBase> baseRenderers { get; }

        // specify vertex count and layout
        protected VertexAttributeDescriptor[] layout =
        {
            new VertexAttributeDescriptor(VertexAttribute.Position, VertexAttributeFormat.Float32, 3,0),
            new VertexAttributeDescriptor(VertexAttribute.Normal, VertexAttributeFormat.Float32, 3,0),
            new VertexAttributeDescriptor(VertexAttribute.Tangent, VertexAttributeFormat.Float32, 4,0),
            new VertexAttributeDescriptor(VertexAttribute.Color, VertexAttributeFormat.Float32, 4,0),
            new VertexAttributeDescriptor(VertexAttribute.TexCoord0, VertexAttributeFormat.Float32, 2,1),
            new VertexAttributeDescriptor(VertexAttribute.TexCoord1, VertexAttributeFormat.Float32, 2,1),
            new VertexAttributeDescriptor(VertexAttribute.TexCoord2, VertexAttributeFormat.Float32, 2,1),
            new VertexAttributeDescriptor(VertexAttribute.TexCoord3, VertexAttributeFormat.Float32, 2,1),
        };

        static protected ProfilerMarker m_SetupRenderMarker = new ProfilerMarker("SetupClothRendering");
        static protected ProfilerMarker m_RenderMarker = new ProfilerMarker("ClothRendering");

        protected ObiSolver m_Solver;

        protected List<DynamicRenderBatch<ObiClothRendererBase>> batchList = new List<DynamicRenderBatch<ObiClothRendererBase>>();
        protected List<ObiClothRendererBase> sortedRenderers = new List<ObiClothRendererBase>(); /**< temp list used to store renderers sorted by batch.*/

        protected SkinmapDataBatch skinmapData;
        protected MeshDataBatch meshData;

        protected ObiNativeList<int> skinMapIndices; // for each renderer, its skinmap index.
        protected ObiNativeList<int> meshIndices; // for each renderer, its mesh index.

        protected ObiNativeList<int> vertexOffsets;   /**< for each renderer, vertex offset in its batch mesh data.*/
        protected ObiNativeList<int> particleOffsets; /**< for each renderer, particle offset in its batch data.*/


        public ObiClothRenderSystem(ObiSolver solver)
        {
            m_Solver = solver;

            skinmapData = new SkinmapDataBatch();
            meshData = new MeshDataBatch();

            skinMapIndices = new ObiNativeList<int>();
            meshIndices = new ObiNativeList<int>();

            vertexOffsets = new ObiNativeList<int>();
            particleOffsets = new ObiNativeList<int>();
        }

        public virtual void Dispose()
        {
            for (int i = 0; i < batchList.Count; ++i)
                batchList[i].Dispose();
            batchList.Clear();

            skinmapData.Dispose();
            meshData.Dispose();

            if (skinMapIndices != null)
                skinMapIndices.Dispose();
            if (meshIndices != null)
                meshIndices.Dispose();

            if (vertexOffsets != null)
                vertexOffsets.Dispose();
            if (particleOffsets != null)
                particleOffsets.Dispose();
        }

        protected virtual void Clear()
        {
            skinmapData.Clear();
            meshData.Clear();

            skinMapIndices.Clear();
            meshIndices.Clear();
            vertexOffsets.Clear();
            particleOffsets.Clear();

            for (int i = 0; i < batchList.Count; ++i)
                batchList[i].Dispose();
            batchList.Clear();

            meshData.InitializeStaticData();
            meshData.InitializeTempData();
        }

        protected virtual void CreateBatches()
        {
            // generate one batch per renderer:
            sortedRenderers.Clear();
            for (int i = 0; i < baseRenderers.Count; ++i)
            {
                int vertexCount = baseRenderers[i].vertexCount * (int)baseRenderers[i].meshInstances;
                batchList.Add(new DynamicRenderBatch<ObiClothRendererBase>(i, vertexCount, baseRenderers[i].materials, new RenderBatchParams(baseRenderers[i].sourceRenderer)));
                sortedRenderers.Add(baseRenderers[i]);
            }

            // sort batches:
            batchList.Sort();

            // reorder renderers based on sorted batches:
            sortedRenderers.Clear();
            for (int i = 0; i < batchList.Count; ++i)
            {
                var batch = batchList[i];

                // write renderers in the order dictated by the sorted batch:
                sortedRenderers.Add(baseRenderers[batch.firstRenderer]);
                batch.firstRenderer = i;
            }
        }

        protected virtual void PopulateBatches()
        {
            // store per-mesh data 
            for (int i = 0; i < sortedRenderers.Count; ++i)
            {
                // add skinmap index:
                skinMapIndices.Add(skinmapData.AddSkinmap(sortedRenderers[i].skinMap, sortedRenderers[i].sourceMesh.bindposes));

                // add mesh index
                meshIndices.Add(meshData.AddMesh(sortedRenderers[i]));
            }
        }

        protected void CalculateOffsets()
        {
            vertexOffsets.ResizeUninitialized(sortedRenderers.Count);
            particleOffsets.ResizeInitialized(sortedRenderers.Count);

            for (int i = 0; i < batchList.Count; ++i)
            {
                var batch = batchList[i];

                int vtxCount = 0;
                int ptCount = 0;

                // Calculate vertex and triangle offsets for each renderer in the batch:
                for (int j = batch.firstRenderer; j < batch.firstRenderer + batch.rendererCount; ++j)
                {
                    vertexOffsets[j] = vtxCount;
                    particleOffsets[j] = ptCount;

                    vtxCount += meshData.GetVertexCount(meshIndices[j]);
                    ptCount += sortedRenderers[j].actor.particleCount;
                }
            }
        }

        protected virtual void CloseBatches()
        {
            meshData.DisposeOfStaticData();
            meshData.DisposeOfTempData();
        }

        public virtual void Setup()
        {
            using (m_SetupRenderMarker.Auto())
            {
                Clear();

                CreateBatches();

                PopulateBatches();

                ObiUtils.MergeBatches(batchList);

                CalculateOffsets();

                CloseBatches();
            }
        }

        public virtual void Step()
        {
        }

        public void BakeMesh(ObiClothRendererBase renderer, ref Mesh mesh, bool transformToActorLocalSpace = false)
        {
            int index = sortedRenderers.IndexOf(renderer);

            for (int i = 0; i < batchList.Count; ++i)
            {
                var batch = batchList[i];
                if (index >= batch.firstRenderer && index < batch.firstRenderer + batch.rendererCount)
                {
                    batch.BakeMesh(sortedRenderers, renderer, ref mesh, transformToActorLocalSpace);
                    return;
                }
            }
        }
    }
}

