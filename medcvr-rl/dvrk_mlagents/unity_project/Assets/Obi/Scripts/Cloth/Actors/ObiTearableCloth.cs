using UnityEngine;
using Unity.Profiling;
using System;
using System.Collections.Generic;

namespace Obi
{
    [AddComponentMenu("Physics/Obi/Obi Tearable Cloth", 901)]
    public class ObiTearableCloth : ObiClothBase
    {
        static ProfilerMarker m_TearingPerfMarker = new ProfilerMarker("ClothTearing");

        public ObiTearableClothBlueprint m_TearableClothBlueprint;
        private ObiTearableClothBlueprint m_TearableBlueprintInstance;

        public bool tearingEnabled = true;
        public float tearResistanceMultiplier = 1000;                   /**< Factor that controls how much a structural cloth spring can stretch before breaking.*/
        public int tearRate = 1;
        [Range(0, 1)] public float tearDebilitation = 0.5f;

        private HashSet<ObiMesh.Cluster> neighborVertices = new HashSet<ObiMesh.Cluster>();
        private List<StructuralConstraint> tornEdges = new List<StructuralConstraint>();
        private List<int> updatedHalfEdges = new List<int>();
        private List<ObiMesh.Triangle> updatedFaces = new List<ObiMesh.Triangle>();
        private List<ObiMesh.Triangle> otherFaces = new List<ObiMesh.Triangle>();

        public override ObiActorBlueprint sourceBlueprint
        {
            get { return m_TearableClothBlueprint; }
        }

        public override ObiClothBlueprintBase clothBlueprintBase
        {
            get { return m_TearableClothBlueprint; }
        }

        public ObiTearableClothBlueprint clothBlueprint
        {
            get { return m_TearableClothBlueprint; }
            set
            {
                if (m_TearableClothBlueprint != value)
                {
                    RemoveFromSolver();
                    ClearState();
                    m_TearableClothBlueprint = value;
                    AddToSolver();
                }
            }
        }

        public delegate void ClothTornCallback(ObiTearableCloth cloth, ObiClothTornEventArgs tearInfo);
        public event ClothTornCallback OnClothTorn;  /**< Called when a constraint is torn.*/

        public class ObiClothTornEventArgs
        {
            public StructuralConstraint edge;       /**< info about the edge being torn.*/
            public int particleIndex;   /**< index of the particle being torn*/
            public List<ObiMesh.Triangle> updatedFaces;

            public ObiClothTornEventArgs(StructuralConstraint edge, int particle, List<ObiMesh.Triangle> updatedFaces)
            {
                this.edge = edge;
                this.particleIndex = particle;
                this.updatedFaces = updatedFaces;
            }
        }

        public override void LoadBlueprint(ObiSolver solver)
        {
            // create a copy of the blueprint for this cloth:
            m_TearableBlueprintInstance = this.blueprint as ObiTearableClothBlueprint;

            base.LoadBlueprint(solver);
        }

        public override void UnloadBlueprint(ObiSolver solver)
        {
            base.UnloadBlueprint(solver);

            // delete the blueprint instance:
            if (m_TearableBlueprintInstance != null)
                DestroyImmediate(m_TearableBlueprintInstance);
        }

        private void SetupRuntimeConstraints()
        {
            SetConstraintsDirty(Oni.ConstraintType.Distance);
            SetConstraintsDirty(Oni.ConstraintType.Bending);
            SetConstraintsDirty(Oni.ConstraintType.Aerodynamics);
            SetSelfCollisions(selfCollisions);
            SetSimplicesDirty();
        }

        protected override void OnValidate()
        {
            base.OnValidate();
            SetupRuntimeConstraints();
        }

        public override void SimulationStart(float timeToSimulate, float substepTime)
        {
            base.SimulationStart(timeToSimulate, substepTime);

            if (isActiveAndEnabled && tearingEnabled)
                ApplyTearing(substepTime);
        }

        private void ApplyTearing(float substepTime)
        {
            using (m_TearingPerfMarker.Auto())
            {
                tornEdges.Clear();
                float sqrTime = substepTime * substepTime;

                var dc = GetConstraintsByType(Oni.ConstraintType.Distance) as ObiConstraints<ObiDistanceConstraintsBatch>;
                var sc = this.solver.GetConstraintsByType(Oni.ConstraintType.Distance) as ObiConstraints<ObiDistanceConstraintsBatch>;

                if (dc != null && sc != null)
                {
                    // iterate up to the amount of entries in solverBatchOffsets, insteaf of dc.batchCount. This ensures
                    // the batches we access have been added to the solver, as solver.UpdateConstraints() could have not been called yet on a newly added actor.
                    for (int j = 0; j < solverBatchOffsets[(int)Oni.ConstraintType.Distance].Count; ++j)
                    {
                        var batch = dc.batches[j] as ObiDistanceConstraintsBatch;
                        var solverBatch = sc.batches[j] as ObiDistanceConstraintsBatch;

                        for (int i = 0; i < batch.activeConstraintCount; i++)
                        {
                            float p1Resistance = m_TearableBlueprintInstance.tearResistance[batch.particleIndices[i * 2]];
                            float p2Resistance = m_TearableBlueprintInstance.tearResistance[batch.particleIndices[i * 2 + 1]];

                            // average particle resistances:
                            float resistance = (p1Resistance + p2Resistance) * 0.5f * tearResistanceMultiplier;

                            // divide lambda by squared delta time to get force in newtons:
                            int offset = solverBatchOffsets[(int)Oni.ConstraintType.Distance][j];
                            float force = solverBatch.lambdas[offset + i] / sqrTime;

                            if (-force > resistance)
                            { // units are newtons.
                                tornEdges.Add(new StructuralConstraint(batch, i, force));
                            }
                        }
                    }
                }

                if (tornEdges.Count > 0)
                {

                    // sort edges by tear force:
                    tornEdges.Sort(delegate (StructuralConstraint x, StructuralConstraint y)
                    {
                        return x.force.CompareTo(y.force);
                    });

                    int tornCount = 0;
                    for (int i = 0; i < tornEdges.Count; i++)
                    {
                        if (Tear(tornEdges[i]))
                            tornCount++;
                        if (tornCount >= tearRate)
                            break;
                    }

                }

            }

        }

        /**
         * Tears a cloth distance constraint, affecting both the physical representation of the cloth and its mesh.
         */
        public bool Tear(StructuralConstraint edge)
        {
            // don't allow splitting if there are no free particles left in the pool.
            if (activeParticleCount >= m_TearableClothBlueprint.particleCount)
                return false;

            // get actor particle indices at both ends of the constraint:
            ParticlePair indices = edge.batchIndex.GetParticleIndices(edge.constraintIndex);

            // Try to perform a split operation on the topology. If we cannot perform it, bail out.
            Vector3 point, normal;
            if (!TopologySplitAttempt(ref indices.first, ref indices.second, out point, out normal))
                return false;

            // Weaken edges around the cut:
            WeakenCutPoint(indices.first, point, normal);

            // split the particle in two, adding a new active particle:
            SplitParticle(indices.first);

            // update constraints:
            UpdateTornDistanceConstraints(indices.first);
            UpdateTornBendConstraints(indices.first);

            solver.dirtyDeformableTriangles = true;

            if (OnClothTorn != null)
                OnClothTorn(this, new ObiClothTornEventArgs(edge, indices.first, updatedFaces));

            return true;
        }


        private bool TopologySplitAttempt(ref int splitActorIndex,
                                          ref int intactActorIndex,
                                          out Vector3 point,
                                          out Vector3 normal)
        {
            int splitSolverIndex = solverIndices[splitActorIndex];
            int intactSolverIndex = solverIndices[intactActorIndex];

            // we will first try to split the particle with higher mass, so swap them if needed.
            if (m_Solver.invMasses[splitSolverIndex] > m_Solver.invMasses[intactSolverIndex])
                ObiUtils.Swap(ref splitSolverIndex, ref intactSolverIndex);

            // Calculate the splitting plane:
            point = m_Solver.positions[splitSolverIndex];
            Vector3 v2 = m_Solver.positions[intactSolverIndex];
            normal = (v2 - point).normalized;

            // Try to split the vertex at that particle. 
            // If we cannot not split the higher mass particle, try the other one. If that fails too, we cannot tear this edge.
            if (m_Solver.invMasses[splitSolverIndex] == 0 ||
                !SplitTopologyAtVertex(splitActorIndex, new Plane(normal, point)))
            {
                // Try to split the other particle:
                ObiUtils.Swap(ref splitActorIndex, ref intactActorIndex);
                ObiUtils.Swap(ref splitSolverIndex, ref intactSolverIndex);

                point = m_Solver.positions[splitSolverIndex];
                v2 = m_Solver.positions[intactSolverIndex];
                normal = (v2 - point).normalized;

                if (m_Solver.invMasses[splitSolverIndex] == 0 ||
                    !SplitTopologyAtVertex(splitActorIndex, new Plane(normal, point)))
                    return false;
            }
            return true;
        }

        private void SplitParticle(int splitActorIndex)
        {
            int splitSolverIndex = solverIndices[splitActorIndex];

            // halve the original particle's mass and radius:
            m_Solver.invMasses[splitSolverIndex] *= 2;
            m_Solver.principalRadii[splitSolverIndex] *= 0.5f;

            // create a copy of the original particle:
            m_TearableBlueprintInstance.tearResistance[activeParticleCount] = m_TearableBlueprintInstance.tearResistance[splitActorIndex];

            CopyParticle(splitActorIndex, activeParticleCount);
            ActivateParticle();
            SetRenderingDirty(Oni.RenderingSystemType.TearableCloth | Oni.RenderingSystemType.Particles | Oni.RenderingSystemType.InstancedParticles);
        }

        private void WeakenCutPoint(int splitActorIndex, Vector3 point, Vector3 normal)
        {
            int weakPt1 = -1;
            int weakPt2 = -1;
            float weakestValue = float.MaxValue;
            float secondWeakestValue = float.MaxValue;

            m_TearableBlueprintInstance.topology.clusters[splitActorIndex].GetNeighbourVertices(neighborVertices);
            foreach (var v in neighborVertices)
            {
                Vector3 neighbour = m_Solver.positions[solverIndices[v.index]];
                float weakness = Mathf.Abs(Vector3.Dot(normal, (neighbour - point).normalized));

                if (weakness < weakestValue)
                {
                    secondWeakestValue = weakestValue;
                    weakestValue = weakness;
                    weakPt2 = weakPt1;
                    weakPt1 = v.index;
                }
                else if (weakness < secondWeakestValue)
                {
                    secondWeakestValue = weakness;
                    weakPt2 = v.index;
                }
            }

            // reduce tear resistance at the weak spots of the cut, to encourage coherent tear formation.
            if (weakPt1 >= 0) m_TearableBlueprintInstance.tearResistance[weakPt1] *= 1 - tearDebilitation;
            if (weakPt2 >= 0) m_TearableBlueprintInstance.tearResistance[weakPt2] *= 1 - tearDebilitation;
        }

        private void ClassifyFaces(int vertex,
                                   Plane plane,
                                   List<ObiMesh.Triangle> side1,
                                   List<ObiMesh.Triangle> side2)
        {
            foreach (var t in m_TearableBlueprintInstance.topology.clusters[vertex].incidentTriangles)
            {
                // calculate actual face center from deformed vertex positions:
                Vector3 faceCenter = (m_Solver.positions[solverIndices[t[0].index]] +
                                      m_Solver.positions[solverIndices[t[1].index]] +
                                      m_Solver.positions[solverIndices[t[2].index]]) * 0.33f;

                if (plane.GetSide(faceCenter))
                    side1.Add(t);
                else
                    side2.Add(t);
            }
        }

        private bool SplitTopologyAtVertex(int vertexIndex,
                                           Plane plane)
        {
            if (vertexIndex < 0 || vertexIndex >= m_TearableBlueprintInstance.topology.clusters.Count)
                return false;

            updatedFaces.Clear();
            updatedHalfEdges.Clear();
            otherFaces.Clear();

            // classify adjacent faces depending on which side of the plane they're at:
            ClassifyFaces(vertexIndex, plane, updatedFaces, otherFaces);

            // guard against pathological case in which all particles are in one side of the plane:
            if (otherFaces.Count == 0 || updatedFaces.Count == 0)
                return false;

            foreach (var t in updatedFaces)
            {
                // determine edges incident to vertex and mark them to update their constraint.
                for (int i = 0; i < 3; ++i)
                {
                    // if the edge references our vertex, store edge index:
                    if (t[i].index == vertexIndex || t[(i + 1) % 3].index == vertexIndex)
                        updatedHalfEdges.Add(t.index * 3 + i);
                }
            }

            // create new vertex:
            m_TearableBlueprintInstance.topology.SplitCluster(updatedFaces, vertexIndex);

            //TODO: update mesh info. (mesh cannot be closed now)

            return true;
        }

        private void UpdateTornDistanceConstraints(int vertexIndex)
        {
            var distanceConstraints = GetConstraintsByType(Oni.ConstraintType.Distance) as ObiConstraints<ObiDistanceConstraintsBatch>;

            foreach (int edgeIndex in updatedHalfEdges)
            {
                Vector2Int constraintDescriptor = m_TearableClothBlueprint.distanceConstraintMap[edgeIndex];

                // get batch and index of the constraint:
                var batch = distanceConstraints.batches[constraintDescriptor.x] as ObiDistanceConstraintsBatch;
                int index = batch.GetConstraintIndex(constraintDescriptor.y);

                // update constraint particle indices:
                int triIndex = edgeIndex / 3;
                int indexInFace = edgeIndex % 3;

                batch.particleIndices[index * 2] = m_TearableBlueprintInstance.topology.triangles[triIndex][indexInFace].index;
                batch.particleIndices[index * 2 + 1] = m_TearableBlueprintInstance.topology.triangles[triIndex][(indexInFace + 1) % 3].index;

                // make sure the constraint is active, in case it is a newly added one.
                batch.ActivateConstraint(index);

                // update deformable triangles:
                m_TearableBlueprintInstance.deformableTriangles[edgeIndex] = m_TearableBlueprintInstance.topology.triangles[triIndex][indexInFace].index;
            }

            foreach (var t in otherFaces)
            {
                for (int i = 0; i < 3; ++i)
                {
                    // if the edge references our vertex:
                    if (t[i].index == vertexIndex || t[(i + 1) % 3].index == vertexIndex)
                    {
                        Vector2Int constraintDescriptor = m_TearableClothBlueprint.distanceConstraintMap[t.index * 3 + i];

                        // get batch and index of the constraint:
                        var batch = distanceConstraints.batches[constraintDescriptor.x] as ObiDistanceConstraintsBatch;
                        int index = batch.GetConstraintIndex(constraintDescriptor.y);

                        // make sure the constraint is active, in case it is a newly added one.
                        batch.ActivateConstraint(index);
                    }
                }
            }

            solver.dirtyConstraints |= (1 << (int)Oni.ConstraintType.Distance);
        }

        private void UpdateTornBendConstraints(int splitActorIndex)
        {
            var bendConstraints = GetConstraintsByType(Oni.ConstraintType.Bending) as ObiConstraints<ObiBendConstraintsBatch>;

            foreach (ObiBendConstraintsBatch batch in bendConstraints.batches)
            {
                // iterate in reverse order so that swapping due to deactivation does not cause us to skip constraints.
                for (int i = batch.activeConstraintCount - 1; i >= 0; --i)
                {
                    if (batch.particleIndices[i * 3] == splitActorIndex ||
                        batch.particleIndices[i * 3 + 1] == splitActorIndex ||
                        batch.particleIndices[i * 3 + 2] == splitActorIndex)
                    {
                        batch.DeactivateConstraint(i);
                    }
                }
            }

            solver.dirtyConstraints |= (1 << (int)Oni.ConstraintType.Bending);
        }

        public override void ProvideDeformableTriangles(ObiNativeIntList deformableTriangles, ObiNativeVector2List deformableUVs)
        {
            if (m_TearableBlueprintInstance != null && m_TearableBlueprintInstance.deformableTriangles != null)
            {
                // Send deformable triangle indices to the solver:
                for (int i = 0; i < m_TearableBlueprintInstance.deformableTriangles.Length; ++i)
                    deformableTriangles.Add(solverIndices[m_TearableBlueprintInstance.deformableTriangles[i]]);

                deformableUVs.AddRange(m_TearableBlueprintInstance.triangleUVs);
            }
        }

        public void OnDrawGizmosSelected()
        {
            /*var sc = solver.GetConstraintsByType(Oni.ConstraintType.Distance) as ObiConstraints<ObiDistanceConstraintsBatch>;
            var c = GetConstraintsByType(Oni.ConstraintType.Distance) as ObiConstraints<ObiDistanceConstraintsBatch>;

            int j = 0;
            foreach (ObiDistanceConstraintsBatch batch in sc.batches)
            {

                //Gizmos.color = Color.green;//co[j%12];
                int offset = solverBatchOffsets[(int)Oni.ConstraintType.Distance][j];


                for (int i = 0; i < batch.activeConstraintCount; ++i)
                {
                    int index = i + offset;

                    Gizmos.color = Color.green;

                    Gizmos.DrawLine(solver.positions[batch.particleIndices[i * 2]],
                                    solver.positions[batch.particleIndices[i * 2 + 1]]);
                }
                j++;
            }*/

            /*if (solver == null || !isLoaded) return;

            Color[] co = new Color[12]{
                Color.red,
                Color.yellow,
                Color.blue,
                Color.white,
                Color.black,
                Color.green,
                Color.cyan,
                Color.magenta,
                Color.gray,
                new Color(1,0.7f,0.1f),
                new Color(0.1f,0.6f,0.5f),
                new Color(0.8f,0.1f,0.6f)
            };

            var constraints = solver.GetConstraintsByType(Oni.ConstraintType.Distance) as ObiConstraints<ObiDistanceConstraintsBatch>;


            int j = 0;
            foreach (ObiDistanceConstraintsBatch batch in constraints.batches){

                //Gizmos.color = Color.green;//co[j%12];



                for (int i = 0; i < batch.activeConstraintCount; ++i)
                {

                    Gizmos.color = new Color(0, 0, 1, 0.75f);//co[j % 12];
                    if (j == btch && i == ctr)
                        Gizmos.color = Color.green;

                    Gizmos.DrawLine(solver.positions[batch.particleIndices[i*2]],
                                    solver.positions[batch.particleIndices[i*2+1]]);
                }
                j++;
            }

            var distanceConstraints = GetConstraintsByType(Oni.ConstraintType.Distance) as ObiConstraints<ObiDistanceConstraintsBatch>;

            for (int i = 0; i < 3; ++i)
            {
                int edge = tri * 3 + i;

                {
                    Vector2Int constraintDescriptor = m_TearableClothBlueprint.distanceConstraintMap[edge];

                    // get batch and index of the constraint:
                    var batch = distanceConstraints.batches[constraintDescriptor.x] as ObiDistanceConstraintsBatch;
                    int index = batch.GetConstraintIndex(constraintDescriptor.y);

                    if (!((batch.particleIndices[index * 2] == m_TearableBlueprintInstance.topology.triangles[edge] &&
                        batch.particleIndices[index * 2 + 1] == m_TearableBlueprintInstance.topology.triangles[tri * 3 + (i + 1) % 3])

                        ||

                        (batch.particleIndices[index * 2 + 1] == m_TearableBlueprintInstance.topology.triangles[edge] &&
                        batch.particleIndices[index * 2] == m_TearableBlueprintInstance.topology.triangles[tri * 3 + (i + 1) % 3]))
                        )
                        Debug.Log("caca");

                    Debug.DrawLine(solver.positions[solverIndices[batch.particleIndices[index * 2]]],
                                   solver.positions[solverIndices[batch.particleIndices[index * 2 + 1]]], Color.red);
                }

                Debug.DrawLine(solver.positions[solverIndices[m_TearableBlueprintInstance.topology.triangles[edge]]],
                               solver.positions[solverIndices[m_TearableBlueprintInstance.topology.triangles[tri * 3 + (i+1)%3]]], Color.yellow);
            }

            */


            /*if (!InSolver) return;

            var constraints = GetConstraints(Oni.ConstraintType.Bending) as ObiRuntimeConstraints<ObiBendConstraintsBatch>;

            int j = 0;
            foreach (ObiBendConstraintsBatch batch in constraints.GetBatches())
            {

                for (int i = 0; i < batch.activeConstraintCount; ++i)
                {
                    Gizmos.color = new Color(1,0,0,0.2f);//co[j % 12];
                    if (j == btch && i == ctr)
                        Gizmos.color = Color.green;
                    
                    Gizmos.DrawLine(GetParticlePosition(batch.springIndices[i * 2]),
                                    GetParticlePosition(batch.springIndices[i * 2 + 1]));
                }
                j++;
            }*/


        }

        /*int tri = 0;
        int btch = 0;
        int ctr = 0;
        public void Update()
        {

            var constraints = GetConstraintsByType(Oni.ConstraintType.Distance) as ObiConstraints<ObiDistanceConstraintsBatch>;

            if (Input.GetKeyDown(KeyCode.UpArrow)){
                ctr++;
                if (ctr >= constraints.batches[btch].activeConstraintCount)
                {
                    btch++;
                    ctr = 0;
                }
            }
            if (Input.GetKeyDown(KeyCode.DownArrow))
            {
                ctr--;
                if (ctr < 0)
                {
                    btch--;
                    ctr = constraints.batches[btch].activeConstraintCount-1;
                }
            }

            if (Input.GetKeyDown(KeyCode.U))
            {
                tri++;
            }

            if (Input.GetKeyDown(KeyCode.J))
            {
                tri--;
            }

            if (Input.GetKeyDown(KeyCode.Space)) {

                Tear(new StructuralConstraint(constraints.batches[btch] as IStructuralConstraintBatch,ctr,0));
            }

        }*/

    }

}