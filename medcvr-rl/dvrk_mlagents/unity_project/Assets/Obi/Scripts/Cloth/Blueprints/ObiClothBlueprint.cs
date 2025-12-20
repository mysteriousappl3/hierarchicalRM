using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using System;

namespace Obi
{

    [CreateAssetMenu(fileName = "cloth blueprint", menuName = "Obi/Cloth Blueprint", order = 120)]
    public class ObiClothBlueprint : ObiClothBlueprintBase
    {

        public override bool usesTethers
        {
            get { return true; }
        }

        [Tooltip("Distance below which two vertices will be merged into a single particle, regardless of mesh connectivity.")]
        [Delayed]
        public float vertexWeldDistance = 0.0001f;

        [Tooltip("Resolution of the particle distribution.")]
        [Delayed]
        public float minimumParticleSize = 0;

        protected GraphColoring colorizer;

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
            restOrientations= new Quaternion[m_Topology.clusters.Count];
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
                    Vector3 v2 = Vector3.Scale(scale,n.centroid);
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

            // Deformable triangles:
            IEnumerator dt = GenerateDeformableTriangles(); 

            while (dt.MoveNext())
                yield return dt.Current;

            // Create triangle simplices:
            IEnumerator t = CreateSimplices();

            while (t.MoveNext())
                yield return t.Current;

            // Create distance constraints:
            IEnumerator dc = CreateDistanceConstraints();

            while (dc.MoveNext())
                yield return dc.Current;

            // Create aerodynamic constraints:
            IEnumerator ac = CreateAerodynamicConstraints();

            while (ac.MoveNext())
                yield return ac.Current;
            
            // Create bending constraints:
            IEnumerator bc = CreateBendingConstraints();

            while (bc.MoveNext())
                yield return bc.Current;

            // Create volume constraints:
            IEnumerator vc = CreateVolumeConstraints();

            while (vc.MoveNext())
                yield return vc.Current;
            
        }

        public override void CommitBlueprintChanges()
        {
            base.CommitBlueprintChanges();

            float radius = m_Topology.GetMaxDistanceFromCluster() * Mathf.Max(Mathf.Max(scale.x, scale.y), scale.z) * 1.5f;
            uint maxInfluences = (uint)Mathf.Min(m_Topology.GetMaxClusterNeighborhoodSize(), 4);
            CreateDefaultSkinmap(radius, 1, maxInfluences);
        }

        protected virtual IEnumerator CreateDistanceConstraints()
        {
            distanceConstraintsData = new ObiDistanceConstraintsData();

            var edges = m_Topology.GetUniqueEdges();

            colorizer.Clear();

            for (int i = 0; i < edges.Count; i++)
            {
                colorizer.AddConstraint(new []{ edges[i].x, edges[i].y });

                if (i % 100 == 0)
                    yield return new CoroutineJob.ProgressInfo("ObiCloth: creating structural constraints...", i / (float)edges.Count);
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

                if (i % 100 == 0)
                    yield return new CoroutineJob.ProgressInfo("ObiCloth: batching distance constraints...", i / (float)constraintColors.Count);
            }

            // Set initial amount of active constraints:
            for (int i = 0; i < distanceConstraintsData.batches.Count; ++i)
            {
                distanceConstraintsData.batches[i].activeConstraintCount = distanceConstraintsData.batches[i].constraintCount;
            }
        }

        protected virtual IEnumerator CreateAerodynamicConstraints()
        {
            aerodynamicConstraintsData = new ObiAerodynamicConstraintsData();
            var aeroBatch = new ObiAerodynamicConstraintsBatch();
            aerodynamicConstraintsData.AddBatch(aeroBatch);

            for (int i = 0; i < m_Topology.clusters.Count; i++)
            {
                aeroBatch.AddConstraint(i, areaContribution[i], 1, 1);

                if (i % 500 == 0)
                    yield return new CoroutineJob.ProgressInfo("ObiCloth: generating aerodynamic constraints...", i / (float)m_Topology.clusters.Count);
            }

            // Set initial amount of active constraints:
            for (int i = 0; i < aerodynamicConstraintsData.batches.Count; ++i)
            {
                aerodynamicConstraintsData.batches[i].activeConstraintCount = aerodynamicConstraintsData.batches[i].constraintCount;
            }
        }

        protected virtual IEnumerator CreateBendingConstraints()
        {
            bendConstraintsData = new ObiBendConstraintsData();

            colorizer.Clear();

            Dictionary<int, int> cons = new Dictionary<int, int>();
            HashSet<ObiMesh.Cluster> neighbors = new HashSet<ObiMesh.Cluster>();
            for (int i = 0; i < m_Topology.clusters.Count; ++i)
            {
                var c = m_Topology.clusters[i];
                c.GetNeighbourVertices(neighbors);
                Vector3 cPos = Vector3.Scale(scale, c.centroid);

                foreach (var n1 in neighbors)
                {

                    float cosBest = 0;
                    var vBest = n1;
                    Vector3 n1Pos = Vector3.Scale(scale, n1.centroid);

                    foreach (var n2 in neighbors)
                    {
                        Vector3 n2Pos = Vector3.Scale(scale, n2.centroid);

                        float cos = Vector3.Dot((n1Pos - cPos).normalized,
                                                (n2Pos - cPos).normalized);
                        if (cos < cosBest)
                        {
                            cosBest = cos;
                            vBest = n2;
                        }
                    }

                    if (!cons.ContainsKey(vBest.index) || cons[vBest.index] != n1.index)
                    {
                        cons[n1.index] = vBest.index;
                        colorizer.AddConstraint(new []{ n1.index, vBest.index, i });
                    }

                }

                if (i % 100 == 0)
                    yield return new CoroutineJob.ProgressInfo("ObiCloth: creating bend constraints...", i / (float)m_Topology.clusters.Count);
            }

            List<int> constraintColors = new List<int>();
            var colorize = colorizer.Colorize("ObiCloth: coloring bend constraints...", constraintColors);
            while (colorize.MoveNext())
                yield return colorize.Current;

            var particleIndices = colorizer.particleIndices;
            var constraintIndices = colorizer.constraintIndices;

            for (int i = 0; i < constraintColors.Count; ++i)
            {
                int color = constraintColors[i];
                int cIndex = constraintIndices[i];

                // Add a new batch if needed:
                if (color >= bendConstraintsData.batchCount)
                    bendConstraintsData.AddBatch(new ObiBendConstraintsBatch());

                Vector3 n1 = m_Topology.clusters[particleIndices[cIndex]].centroid;
                Vector3 vBest = m_Topology.clusters[particleIndices[cIndex + 1]].centroid;
                Vector3 vertex = m_Topology.clusters[particleIndices[cIndex + 2]].centroid;

                Vector3 n1Pos = Vector3.Scale(scale,n1);
                Vector3 bestPos = Vector3.Scale(scale,vBest);
                Vector3 vertexPos = Vector3.Scale(scale,vertex);

                float restBend = ObiUtils.RestBendingConstraint(n1Pos,bestPos,vertexPos);
                bendConstraintsData.batches[color].AddConstraint(new Vector3Int(particleIndices[cIndex], particleIndices[cIndex + 1], particleIndices[cIndex + 2]), restBend);

                if (i % 100 == 0)
                    yield return new CoroutineJob.ProgressInfo("ObiCloth: batching bend constraints...", i / (float)constraintColors.Count);
            }

            // Set initial amount of active constraints:
            for (int i = 0; i < bendConstraintsData.batches.Count; ++i)
            {
                bendConstraintsData.batches[i].activeConstraintCount = bendConstraintsData.batches[i].constraintCount;
            }
        }

        protected virtual IEnumerator CreateVolumeConstraints()
        {
            //Create pressure constraints if the mesh is closed:
            if (m_Topology.GetBorderClusterCount() == 0)
            {
                volumeConstraintsData = new ObiVolumeConstraintsData();

                ObiVolumeConstraintsBatch volumeBatch = new ObiVolumeConstraintsBatch();
                volumeConstraintsData.AddBatch(volumeBatch);

                float avgInitialScale = (scale.x + scale.y + scale.z) * 0.33f;

                float volume = 0;
                int[] triangleIndices = new int[m_Topology.triangles.Count * 3];
                for (int i = 0; i < m_Topology.triangles.Count; i++)
                {
                    var face = topology.triangles[i];

                    triangleIndices[i * 3] = face[0].index;
                    triangleIndices[i * 3 + 1] = face[1].index;
                    triangleIndices[i * 3 + 2] = face[2].index;

                    volume += ObiUtils.TetraVolume(face[0].centroid, face[01].centroid, face[2].centroid);

                    if (i % 500 == 0)
                        yield return new CoroutineJob.ProgressInfo("ObiCloth: generating volume constraints...", i / (float)m_Topology.triangles.Count);
                }

                volumeBatch.AddConstraint(triangleIndices, volume * avgInitialScale);

                // Set initial amount of active constraints:
                for (int i = 0; i < volumeConstraintsData.batches.Count; ++i)
                {
                    volumeConstraintsData.batches[i].activeConstraintCount = volumeConstraintsData.batches[i].constraintCount;
                }
            }
        }

        public override void ClearTethers()
        {
            tetherConstraintsData.Clear();
        }

        private List<HashSet<int>> GenerateIslands(IEnumerable<int> particles, Func<int, bool> condition)
        {
            List<HashSet<int>> islands = new List<HashSet<int>>();

            var neighbors = new HashSet<ObiMesh.Cluster>();

            // Partition fixed particles into islands:
            foreach (int i in particles)
            {
                var vertex = m_Topology.clusters[i];

                if (condition != null && !condition(i)) continue;

                int assignedIsland = -1;

                // keep a list of islands to merge with ours:
                List<int> mergeableIslands = new List<int>();

                // See if any of our neighbors is part of an island:
                vertex.GetNeighbourVertices(neighbors);
                foreach (var n in neighbors)
                {

                    for (int k = 0; k < islands.Count; ++k)
                    {

                        if (islands[k].Contains(n.index))
                        {

                            // if we are not in an island yet, pick this one:
                            if (assignedIsland < 0)
                            {
                                assignedIsland = k;
                                islands[k].Add(i);
                            }
                            // if we already are in an island, we will merge this newfound island with ours:
                            else if (assignedIsland != k && !mergeableIslands.Contains(k))
                            {
                                mergeableIslands.Add(k);
                            }
                        }
                    }
                }

                // merge islands with the assigned one:
                foreach (int merge in mergeableIslands)
                {
                    islands[assignedIsland].UnionWith(islands[merge]);
                }

                // remove merged islands:
                mergeableIslands.Sort();
                mergeableIslands.Reverse();
                foreach (int merge in mergeableIslands)
                {
                    islands.RemoveAt(merge);
                }

                // If no adjacent particle is in an island, create a new one:
                if (assignedIsland < 0)
                {
                    islands.Add(new HashSet<int>() { i });
                }
            }

            return islands;
        }

        /**
         * Automatically generates tether constraints for the cloth.
         * Partitions fixed particles into "islands", then generates up to maxTethers constraints for each 
         * particle, linking it to the closest point in each island.
         */
        public override void GenerateTethers(bool[] selected)
        {

            tetherConstraintsData = new ObiTetherConstraintsData();

            // generate disjoint groups of particles (islands)
            List<HashSet<int>> islands = GenerateIslands(System.Linq.Enumerable.Range(0, m_Topology.clusters.Count), null);

            // generate tethers for each one:
            List<int> particleIndices = new List<int>();
            foreach (HashSet<int> island in islands)
                GenerateTethersForIsland(island,particleIndices,selected,4);

            // for tethers, it's easy to use the optimal amount of colors analytically.
            if (particleIndices.Count > 0)
            {
                int color = 0;
                int lastParticle = particleIndices[0];
                for (int i = 0; i < particleIndices.Count; i += 2)
                {

                    if (particleIndices[i] != lastParticle)
                    {
                        lastParticle = particleIndices[i];
                        color = 0;
                    }

                    // Add a new batch if needed:
                    if (color >= tetherConstraintsData.batchCount)
                        tetherConstraintsData.AddBatch(new ObiTetherConstraintsBatch());

                    var startVertex = m_Topology.clusters[particleIndices[i]];
                    var endVertex = m_Topology.clusters[particleIndices[i + 1]];

                    tetherConstraintsData.batches[color].AddConstraint(new Vector2Int(particleIndices[i], particleIndices[i + 1]),
                                                                       Vector3.Distance(Vector3.Scale(scale, startVertex.centroid), Vector3.Scale(scale, endVertex.centroid)),
                                                                       1);
                    color++;
                }
            }

            // Set initial amount of active constraints:
            for (int i = 0; i < tetherConstraintsData.batches.Count; ++i)
            {
                tetherConstraintsData.batches[i].activeConstraintCount = tetherConstraintsData.batches[i].constraintCount;
            }
        }

        /**
         * This function generates tethers for a given set of particles, all belonging a connected graph. 
         * This is use ful when the cloth mesh is composed of several
         * disjoint islands, and we dont want tethers in one island to anchor particles to fixed particles in a different island.
         * 
         * Inside each island, fixed particles are partitioned again into "islands", then generates up to maxTethers constraints for each 
         * particle linking it to the closest point in each fixed island.
         */
        private void GenerateTethersForIsland(HashSet<int> particles, List<int> particleIndices, bool[] selected, int maxTethers)
        {
            if (maxTethers > 0)
            {
                List<HashSet<int>> fixedIslands = GenerateIslands(particles,(x => selected[x]));

                // Generate tether constraints:
                foreach (int i in particles)
                {
                    // Skip inactive particles.
                    if (!IsParticleActive(i) || selected[i]) 
                        continue;

                    List<KeyValuePair<float,int>> tethers = new List<KeyValuePair<float,int>>(fixedIslands.Count*maxTethers);

                    // Find the closest particle in each island, and add it to tethers.
                    foreach(HashSet<int> island in fixedIslands)
                    {
                        int closest = -1;
                        float minDistance = Mathf.Infinity;
                        foreach (int j in island)
                        {
                            float distance = (m_Topology.clusters[i].centroid - m_Topology.clusters[j].centroid).sqrMagnitude;
                            if (distance < minDistance && i != j)
                            {
                                minDistance = distance;
                                closest = j;
                            }
                        }
                        if (closest >= 0)
                            tethers.Add(new KeyValuePair<float,int>(minDistance, closest));
                    }

                    // Sort tether indices by distance:
                    tethers.Sort(
                    delegate(KeyValuePair<float,int> x, KeyValuePair<float,int> y)
                    {
                        return x.Key.CompareTo(y.Key);
                    }
                    );

                    // Create constraints for "maxTethers" closest anchor particles:
                    for (int k = 0; k < Mathf.Min(maxTethers,tethers.Count); ++k){
                        particleIndices.Add(i);
                        particleIndices.Add(tethers[k].Value); // the second particle is the anchor (assumed to be fixed)
                    }
                }
            }
        }
    }
}