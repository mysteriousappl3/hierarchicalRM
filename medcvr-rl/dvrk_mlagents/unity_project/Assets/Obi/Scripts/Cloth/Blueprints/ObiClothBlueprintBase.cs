using System.Collections;
using UnityEngine;

#if UNITY_EDITOR
using UnityEditor;
#endif

namespace Obi
{
    public abstract class ObiClothBlueprintBase : ObiMeshBasedActorBlueprint
    {         
        [SerializeField] [HideInInspector] protected ObiMesh m_Topology;  /**< Topology generated from the input mesh.*/
        [SerializeField] [HideInInspector] protected ObiSkinMap m_Skinmap;

        [HideInInspector] public int[] deformableTriangles = null;    /**< Indices of deformable triangles (3 per triangle)*/
        [HideInInspector] public Vector2[] triangleUVs = null;        /**< Deformable triangle UVS (3 per triangle). */

        [HideInInspector] public Vector3[] restNormals = null;
        [HideInInspector] public float[] areaContribution = null;           /**< How much mesh surface area each particle represents.*/

        public const float DEFAULT_PARTICLE_MASS = 0.1f;

        public ObiMesh topology => m_Topology;
        public ObiSkinMap defaultSkinmap => m_Skinmap;

        protected override void SwapWithFirstInactiveParticle(int index)
        {
            base.SwapWithFirstInactiveParticle(index);

            areaContribution.Swap(index, m_ActiveParticleCount);
            restNormals.Swap(index, m_ActiveParticleCount);

            // Keep topology in sync:
            if (topology != null) //&& topology.containsData)
            {
                topology.SwapClusters(index, m_ActiveParticleCount);
            }

            // Keep deformable triangles in sync:
            for (int i = 0; i < deformableTriangles.Length; ++i)
            {
                if (deformableTriangles[i] == index)
                    deformableTriangles[i] = m_ActiveParticleCount;
                else if (deformableTriangles[i] == m_ActiveParticleCount)
                    deformableTriangles[i] = index;
            }
        }

        protected virtual IEnumerator GenerateDeformableTriangles() 
        {
            deformableTriangles = new int[m_Topology.triangles.Count * 3];
            triangleUVs = new Vector2[m_Topology.triangles.Count * 3];
            restNormals = new Vector3[m_Topology.clusters.Count];

            // Generate deformable triangles:
            for (int i = 0; i < m_Topology.triangles.Count; ++i)
            {
                int i1 = m_Topology.triangles[i][0].index;
                int i2 = m_Topology.triangles[i][1].index;
                int i3 = m_Topology.triangles[i][2].index;

                deformableTriangles[i * 3] = i1;
                deformableTriangles[i * 3 + 1] = i2;
                deformableTriangles[i * 3 + 2] = i3;

                restNormals[i1] += m_Topology.triangles[i].normal;
                restNormals[i2] += m_Topology.triangles[i].normal;
                restNormals[i3] += m_Topology.triangles[i].normal;

                ObiUtils.BestTriangleAxisProjection(m_Topology.triangles[i][0].centroid,
                                                    m_Topology.triangles[i][1].centroid,
                                                    m_Topology.triangles[i][2].centroid,
                                                    out triangleUVs[i * 3],
                                                    out triangleUVs[i * 3 + 1],
                                                    out triangleUVs[i * 3 + 2]);

                if (i % 500 == 0)
                    yield return new CoroutineJob.ProgressInfo("ObiCloth: generating deformable geometry...", i / (float)m_Topology.triangles.Count);
            }

            for (int i = 0; i < restNormals.Length; ++i)
                restNormals[i].Normalize();
        }

        protected virtual IEnumerator CreateSimplices()
        {
            triangles = new int[m_Topology.triangles.Count * 3];
            restNormals = new Vector3[m_Topology.clusters.Count];

            // Generate deformable triangles:
            for (int i = 0; i < m_Topology.triangles.Count; ++i)
            {
                int i1 = m_Topology.triangles[i][0].index;
                int i2 = m_Topology.triangles[i][1].index;
                int i3 = m_Topology.triangles[i][2].index;

                triangles[i * 3] = i1;
                triangles[i * 3 + 1] = i2;
                triangles[i * 3 + 2] = i3;

                restNormals[i1] += m_Topology.triangles[i].normal;
                restNormals[i2] += m_Topology.triangles[i].normal;
                restNormals[i3] += m_Topology.triangles[i].normal;

                if (i % 500 == 0)
                    yield return new CoroutineJob.ProgressInfo("ObiCloth: generating deformable geometry...", i / (float)m_Topology.triangles.Count);
            }

            for (int i = 0; i < restNormals.Length; ++i)
                restNormals[i].Normalize();
        }

        protected virtual void CreateDefaultSkinmap(float radius, float falloff = 1, uint maxInfluences = 4, bool mapBonesToParticles = false)
        {
            DestroyImmediate(m_Skinmap, true);
            m_Skinmap = CreateInstance<ObiSkinMap>();
            m_Skinmap.name = this.name + " skinmap";
            m_Skinmap.checksum = checksum;

            if (mapBonesToParticles)
                m_Skinmap.MapBonesToParticles(inputMesh, topology, Matrix4x4.identity, Matrix4x4.identity);

            m_Skinmap.MapParticlesToVertices(inputMesh, this, Matrix4x4.TRS(Vector3.zero, rotation, scale), Matrix4x4.identity, radius, falloff, maxInfluences);

#if UNITY_EDITOR
            if (!Application.isPlaying && EditorUtility.IsPersistent(this))
            {
                AssetDatabase.AddObjectToAsset(m_Skinmap, this);
                AssetDatabase.SaveAssetIfDirty(this);
            }
#endif
        }
    }
}