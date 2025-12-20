using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using System;

namespace Obi
{

    [CreateAssetMenu(fileName = "skinned cloth blueprint", menuName = "Obi/Skinned Cloth Blueprint", order = 122)]
    public class ObiSkinnedClothBlueprint : ObiClothBlueprint
    {
        public override bool usesTethers
        {
            get { return true; }
        }

        public override void RemoveSelectedParticles(ref bool[] selected, bool optimize = true)
        {
            base.RemoveSelectedParticles(ref selected, optimize);

            var skinConstraints = GetConstraintsByType(Oni.ConstraintType.Skin);
            if (skinConstraints != null)
            {
                for (int j = 0; j < skinConstraints.batchCount; ++j)
                {
                    // set backstop values to zero for all disabled constraints:
                    var batch = (skinConstraints.GetBatch(j) as ObiSkinConstraintsBatch);
                    for (int i = batch.activeConstraintCount; i < batch.constraintCount; ++i)
                    {
                        batch.skinRadiiBackstop[i * 3] = 0;
                        batch.skinRadiiBackstop[i * 3 + 1] = 0;
                        batch.skinRadiiBackstop[i * 3 + 2] = 0;
                    }

                    // reactivate all skin constraints, since we need to update mesh vertices even when bound to inactive particles:
                    batch.activeConstraintCount = skinConstraints.GetBatch(j).initialActiveConstraintCount;
                }
            }
        }

        protected override IEnumerator Initialize(){

            if (inputMesh == null || !inputMesh.isReadable)
            {
                // TODO: return an error in the coroutine.
                Debug.LogError("The input mesh is null, or not readable.");
                yield break;
            }

            ClearParticleGroups(false, false);

            m_Topology = new ObiMesh();

            var build = m_Topology.Build(inputMesh.vertices, inputMesh.triangles);
            while (build.MoveNext())
                yield return build.Current;

            var weld = m_Topology.Weld(vertexWeldDistance);
            while (weld.MoveNext())
                yield return weld.Current;

            var decimate = m_Topology.Decimate(minimumParticleSize);
            while (decimate.MoveNext())
                yield return decimate.Current;

            positions = new Vector3[m_Topology.clusters.Count];
            restPositions = new Vector4[m_Topology.clusters.Count];
            restOrientations = new Quaternion[m_Topology.clusters.Count];
            velocities = new Vector3[m_Topology.clusters.Count];
            invMasses = new float[m_Topology.clusters.Count];
            principalRadii = new Vector3[m_Topology.clusters.Count];
            filters = new int[m_Topology.clusters.Count];
            colors = new Color[m_Topology.clusters.Count];

            areaContribution = new float[m_Topology.clusters.Count];

            var neighbors = new HashSet<ObiMesh.Cluster>();

            // Create a particle for each vertex:
            m_ActiveParticleCount = m_Topology.clusters.Count;
            for (int i = 0; i < m_Topology.clusters.Count; i++)
            {
                var vertex = m_Topology.clusters[i];

                // Get the particle's area contribution.
                areaContribution[i] = 0;
                foreach (var face in vertex.incidentTriangles)
                {
                    areaContribution[i] += ObiUtils.TriangleArea(face[0].centroid, face[1].centroid, face[2].centroid) / 3;
                }
                areaContribution[i] = Mathf.Max(0.001f, areaContribution[i]);

                // Get the shortest neighbour edge, particle radius will be half of its length.
                vertex.GetNeighbourVertices(neighbors);
                Vector3 v1 = Vector3.Scale(scale, vertex.centroid);
                float minEdgeLength = Single.MaxValue;
                foreach (var n in neighbors)
                {
                    Vector3 v2 = Vector3.Scale(scale, n.centroid);
                    minEdgeLength = Mathf.Min(minEdgeLength, Vector3.Distance(v1, v2));
                }

                invMasses[i] = (areaContribution[i] > 0) ? (1.0f / (DEFAULT_PARTICLE_MASS * areaContribution[i])) : 0;
                positions[i] = v1;
                restPositions[i] = positions[i];
                restPositions[i][3] = 1; // activate rest position.
                restOrientations[i] = vertex.orientation;
                principalRadii[i] = Vector3.one * minEdgeLength * 0.5f;
                filters[i] = ObiUtils.MakeFilter(ObiUtils.CollideWithEverything, 1);
                colors[i] = Color.white;

                if (i % 500 == 0)
                    yield return new CoroutineJob.ProgressInfo("ObiCloth: generating particles...", i / (float)m_Topology.clusters.Count);
            }

            colorizer = new GraphColoring(m_ActiveParticleCount);

            IEnumerator dt = GenerateDeformableTriangles();
            while (dt.MoveNext())
                yield return dt.Current;

            //Create distance constraints:
            IEnumerator dc = CreateDistanceConstraints();

            while (dc.MoveNext())
                yield return dc.Current;

            // Create aerodynamic constraints:
            IEnumerator ac = CreateAerodynamicConstraints();

            while (ac.MoveNext())
                yield return ac.Current;

            //Create bending constraints:
            IEnumerator bc = CreateBendingConstraints();

            while (bc.MoveNext())
                yield return bc.Current;

            // Create skin constraints:
            IEnumerator sc = CreateSkinConstraints();

            while (sc.MoveNext())
                yield return sc.Current;
        }

        public override void CommitBlueprintChanges()
        {
            base.CommitBlueprintChanges();

            float radius = m_Topology.GetMaxDistanceFromCluster() * Mathf.Max(Mathf.Max(scale.x, scale.y), scale.z) * 1.5f;
            uint maxInfluences = (uint)Mathf.Min(m_Topology.GetMaxClusterNeighborhoodSize(), 4);
            CreateDefaultSkinmap(radius, 1, maxInfluences, true);
        }

        protected IEnumerator CreateSkinConstraints()
        {
            skinConstraintsData = new ObiSkinConstraintsData();
            ObiSkinConstraintsBatch skinBatch = new ObiSkinConstraintsBatch();
            skinConstraintsData.AddBatch(skinBatch);

            for (int i = 0; i < topology.clusters.Count; ++i)
            {
                skinBatch.AddConstraint(i, Vector3.Scale(scale,topology.clusters[i].centroid), topology.clusters[i].orientation * Vector3.forward, 0.05f, 0.1f, 0, 0);
                skinBatch.activeConstraintCount++;

                if (i % 500 == 0)
                    yield return new CoroutineJob.ProgressInfo("ObiCloth: generating skin constraints...", i / (float)topology.clusters.Count);
            }
        }

    }
}