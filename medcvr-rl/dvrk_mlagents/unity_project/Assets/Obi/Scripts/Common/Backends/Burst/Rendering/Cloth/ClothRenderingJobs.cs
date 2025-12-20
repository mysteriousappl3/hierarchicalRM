#if (OBI_BURST && OBI_MATHEMATICS && OBI_COLLECTIONS)
using Unity.Jobs;
using Unity.Collections;
using Unity.Mathematics;
using Unity.Burst;
using UnityEngine;

namespace Obi
{
    [BurstCompile]
    struct UpdateSkinJob : IJobParallelFor
    {

        [ReadOnly] public NativeArray<int> rendererIndices;
        [ReadOnly] public NativeArray<int> skinmapIndices;
        [ReadOnly] public NativeArray<int> skeletonIndices;

        [ReadOnly] public NativeArray<int> skinConstraintOffsets;
        [ReadOnly] public NativeArray<int> particleOffsets;
        [ReadOnly] public NativeArray<int> influenceOffsets;

        [ReadOnly] public NativeArray<int> particleIndices;

        [ReadOnly] public NativeArray<float4> restPositions;
        [ReadOnly] public NativeArray<quaternion> restOrientations;

        [ReadOnly] public NativeArray<SkinmapDataBatch.SkinmapData> skinData;
        [ReadOnly] public NativeArray<SkeletonDataBatch.SkeletonData> skeletonData;

        [ReadOnly] public NativeArray<float4x4> boneBindMatrices;

        [ReadOnly] public NativeArray<ObiInfluenceMap.Influence> skinWeights;

        [ReadOnly] public NativeArray<float3> bonePos;
        [ReadOnly] public NativeArray<quaternion> boneRot;
        [ReadOnly] public NativeArray<float3> boneScl;

        [NativeDisableParallelForRestriction] public NativeArray<float4> skinConstraintPoints;
        [NativeDisableParallelForRestriction] public NativeArray<float4> skinConstraintNormals;

        public float4x4 world2Solver;

        public void Execute(int i) // for each renderer:
        {
            int rendererIndex = rendererIndices[i];

            // get skin map and skeleton data:
            var skin = skinData[skinmapIndices[rendererIndex]];
            var skel = skeletonData[skeletonIndices[rendererIndex]];

            // invalid skeleton:
            if (skel.boneCount <= 0)
                return;

            // get index of this particle in its original actor: 
            int originalParticleIndex = i - particleOffsets[rendererIndex];

            // get first influence and amount of influences for this particle:
            int influenceStart = influenceOffsets[skin.firstSkinWeightOffset + originalParticleIndex];
            int influenceCount = influenceOffsets[skin.firstSkinWeightOffset + originalParticleIndex + 1] - influenceStart;

            float4 pos = float4.zero;
            float4 norm = float4.zero;

            for (int k = influenceStart; k < influenceStart + influenceCount; ++k)
            {
                var inf = skinWeights[skin.firstSkinWeight + k];

                float4x4 bind = boneBindMatrices[skin.firstParticleBindPose + inf.index];

                int boneIndex = skel.firstBone + inf.index;
                float4x4 deform = float4x4.TRS(bonePos[boneIndex], boneRot[boneIndex], boneScl[boneIndex]);
                float4x4 trfm = math.mul(world2Solver, math.mul(deform, bind)); // Need world2Solver because bones are expressed in world space.

                pos.xyz += math.mul(trfm, new float4(restPositions[particleIndices[i]].xyz, 1)).xyz * inf.weight;
                norm.xyz += math.mul(trfm, new float4(math.mul(restOrientations[particleIndices[i]], new float3(0, 0, 1)), 0)).xyz * inf.weight;
            }

            int constraintIndex = skinConstraintOffsets[rendererIndex] + originalParticleIndex;
            skinConstraintPoints[constraintIndex] = pos;
            skinConstraintNormals[constraintIndex] = norm;
        }
    }

    [BurstCompile]
    struct UpdateClothMeshJob : IJobParallelFor
    {
        [ReadOnly] public NativeArray<int> rendererIndices;
        [ReadOnly] public NativeArray<int> skinmapIndices;
        [ReadOnly] public NativeArray<int> meshIndices;

        [ReadOnly] public NativeArray<int> vertexOffsets;
        [ReadOnly] public NativeArray<int> particleOffsets;
        [ReadOnly] public NativeArray<int> influenceOffsets;

        [ReadOnly] public NativeArray<int> particleIndices;

        [ReadOnly] public NativeArray<float4> renderablePositions;
        [ReadOnly] public NativeArray<quaternion> renderableOrientations;
        [ReadOnly] public NativeArray<float4> colors;

        [ReadOnly] public NativeArray<SkinmapDataBatch.SkinmapData> skinData;
        [ReadOnly] public NativeArray<MeshDataBatch.MeshData> meshData;

        [ReadOnly] public NativeArray<float4x4> particleBindMatrices;

        [ReadOnly] public NativeArray<ObiInfluenceMap.Influence> influences;

        [ReadOnly] public NativeArray<float3> positions;
        [ReadOnly] public NativeArray<float3> normals;
        [ReadOnly] public NativeArray<float4> tangents;

        public NativeArray<DynamicBatchVertex> vertices;

        public void Execute(int i)
        {
            int rendererIndex = rendererIndices[i];

            // get skin map and mesh data:
            var skin = skinData[skinmapIndices[rendererIndex]];
            var mesh = meshData[meshIndices[rendererIndex]];

            // get index of this vertex in its original mesh:
            int originalVertexIndex = i - vertexOffsets[rendererIndex];

            // get index of the vertex in the mesh batch:
            int batchedVertexIndex = mesh.firstVertex + originalVertexIndex;

            // get first influence and amount of influences for this vertex:
            int influenceStart = influenceOffsets[skin.firstInfOffset + originalVertexIndex];
            int influenceCount = influenceOffsets[skin.firstInfOffset + originalVertexIndex + 1] - influenceStart;

            var vertex = vertices[i];
            vertex.pos = float3.zero;
            vertex.normal = float3.zero;
            vertex.tangent = float4.zero;
            vertex.color = float4.zero;

            for (int k = influenceStart; k < influenceStart + influenceCount; ++k)
            {
                var inf = influences[skin.firstInfluence + k];

                int p = particleIndices[particleOffsets[rendererIndex] + inf.index];

                float4x4 deform = math.mul(float4x4.Translate(renderablePositions[p].xyz), renderableOrientations[p].toMatrix());
                float4x4 trfm = math.mul(deform, particleBindMatrices[skin.firstParticleBindPose + inf.index]);

                // update vertex/normal/tangent:
                vertex.pos += (Vector3)math.mul(trfm, new float4(positions[batchedVertexIndex], 1)).xyz * inf.weight;
                vertex.normal += (Vector3)math.mul(trfm, new float4(normals[batchedVertexIndex], 0)).xyz * inf.weight;
                vertex.tangent += (Vector4)new float4(math.mul(trfm, new float4(tangents[batchedVertexIndex].xyz, 0)).xyz, tangents[batchedVertexIndex].w) * inf.weight;
                vertex.color += (Vector4)colors[p] * inf.weight;
            }

            vertices[i] = vertex;
        }
    }
}
#endif