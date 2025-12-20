using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using System;

namespace Obi
{

    [CreateAssetMenu(fileName = "tearable cloth blueprint", menuName = "Obi/Tearable Cloth Blueprint", order = 121)]
    public class ObiTearableClothBlueprint : ObiClothBlueprint
    {
        [Tooltip("Amount of memory preallocated to create extra particles and mesh data when tearing the cloth. 0 means no extra memory will be allocated, and the cloth will not be tearable. 1 means all cloth triangles will be fully tearable.")]
        [Range(0, 1)]
        public float tearCapacity = 0.5f;

        [HideInInspector] [SerializeField] private int pooledParticles = 0;

        [HideInInspector] public float[] tearResistance;                                 /**< Per-particle tear resistance.*/
        [HideInInspector] [SerializeField] public Vector2Int[] distanceConstraintMap;     /** constraintHalfEdgeMap[half-edge index] = distance constraint index, or -1 if there's no constraint. 
                                                                                               Each initial constraint is the lower-index of each pair of half-edges. When a half-edge is split during
                                                                                               tearing, one of the two half-edges gets its constraint updated and the other gets a new constraint.*/
        public int PooledParticles
        {
            get { return pooledParticles; }
        }

        public override bool usesTethers
        {
            get { return false; }
        }

        protected override IEnumerator Initialize()
        {
            /**
             * Have a map for half-edge->constraint.
             * Initially create all constraints and pre-cook them.
             * Constraints at each side of the same edge, are in different batches.
             */

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

            pooledParticles = (int)((m_Topology.triangles.Count - m_Topology.clusters.Count) * tearCapacity);
            int totalParticles = m_Topology.clusters.Count + pooledParticles;

            positions = new Vector3[totalParticles];
            restPositions = new Vector4[totalParticles];
            restOrientations = new Quaternion[totalParticles];
            velocities = new Vector3[totalParticles];
            invMasses = new float[totalParticles];
            principalRadii = new Vector3[totalParticles];
            filters = new int[totalParticles];
            colors = new Color[totalParticles];

            areaContribution = new float[totalParticles];
            tearResistance = new float[totalParticles];

            // Create a particle for each vertex:
            var neighbors = new HashSet<ObiMesh.Cluster>();

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
                float minEdgeLength = float.MaxValue;
                foreach (var n in neighbors)
                {
                    Vector3 v2 = Vector3.Scale(scale, n.centroid);
                    minEdgeLength = Mathf.Min(minEdgeLength, Vector3.Distance(v1, v2));
                }

                tearResistance[i] = 1;
                invMasses[i] = 1;//(/*skinnedMeshRenderer == null &&*/ areaContribution[i] > 0) ? (1.0f / (DEFAULT_PARTICLE_MASS * areaContribution[i])) : 0;
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

            colorizer = new GraphColoring(totalParticles);

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
        }

        public override void CommitBlueprintChanges()
        {
            base.CommitBlueprintChanges();

            CreateDefaultSkinmap(0.001f, 1, 1);
        }

        protected override IEnumerator CreateDistanceConstraints()
        {
            // prepare an array that maps from triangle edge to <batch, constraintId>
            distanceConstraintMap = new Vector2Int[m_Topology.triangles.Count * 3];
            for (int i = 0; i < distanceConstraintMap.Length; i++)
                distanceConstraintMap[i] = new Vector2Int(-1, -1);

            //Create distance constraints, one for each half-edge.
            distanceConstraintsData = new ObiDistanceConstraintsData();

            IEnumerator dc = CreateInitialDistanceConstraints(m_Topology.edges);
            while (dc.MoveNext())
                yield return dc.Current;
        }

        private IEnumerator CreateInitialDistanceConstraints(List<Vector3Int> edges)
        {
            colorizer.Clear();

            for (int i = 0; i < edges.Count; i++)
            {
                colorizer.AddConstraint(new[] { edges[i].x, edges[i].y });

                if (i % 500 == 0)
                    yield return new CoroutineJob.ProgressInfo("ObiCloth: generating structural constraints...", i / (float)edges.Count);
            }

            List<int> constraintColors = new List<int>();
            var colorize = colorizer.Colorize("ObiCloth: coloring distance constraints...", constraintColors);
            while (colorize.MoveNext())
                yield return colorize.Current;

            var particleIndices = colorizer.particleIndices;
            var constraintIndices = colorizer.constraintIndices;

            for (int i = 0; i < constraintColors.Count; ++i)
            {
                int color = constraintColors[i];
                int cIndex = constraintIndices[i];

                // Add a new batch if needed:
                if (color >= distanceConstraintsData.batchCount)
                    distanceConstraintsData.AddBatch(new ObiDistanceConstraintsBatch());

                Vector3 v1 = Vector3.Scale(scale, m_Topology.clusters[particleIndices[cIndex]].centroid);
                Vector3 v2 = Vector3.Scale(scale, m_Topology.clusters[particleIndices[cIndex + 1]].centroid);

                distanceConstraintsData.batches[color].AddConstraint(new Vector2Int(particleIndices[cIndex], particleIndices[cIndex + 1]),
                                                                     Vector3.Distance(v1, v2));

                distanceConstraintMap[edges[i].z] = new Vector2Int(color, distanceConstraintsData.batches[color].constraintCount - 1);

                if (i == 0 || edges[i].x != edges[i - 1].x || edges[i].y != edges[i - 1].y)
                    distanceConstraintsData.batches[color].ActivateConstraint(distanceConstraintsData.batches[color].constraintCount - 1);
            }
        }
    }
}