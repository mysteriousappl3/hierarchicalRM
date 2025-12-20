using UnityEngine;
using Unity.MLAgents.Sensors;
using Unity.MLAgents.Actuators;
using Obi;
using System.Collections.Generic;
using UnityEngine.UIElements;

public class MultiCutAgent : BaseAgent
{
    [Header("Multi Cut References")]
    // Task Specific Environment References
    // See Parent for generic references
    public ObiSolver Solver;
    public GameObject RopePrefab;
    public GameObject RopeInstance;

    public GameObject ToolMidpoint;
    public GameObject Goal;
    public GameObject CutMarkerPrefab;

    [HideInInspector]
    public MultiCutDetector CutDetector;

    public enum MultiCutVariant {ThreeRopes, MeshStraight, MeshCircle, MeshTriangle}
    public enum RewardMode { Sparse, Dense }
    [Header("Multi Cut Settings")]
    public RewardMode rewardMode = RewardMode.Sparse;
    public MultiCutVariant multiCutVariant = MultiCutVariant.ThreeRopes;

    public int CollisionID = 1;

    public enum CutQuality { Bad, Good, Best };
    public class CutData
    {
        public int solverIndex = -1;
        public bool isCut = false;
        public int goalElementIndex = -1;
        public CutQuality quality = CutQuality.Bad;
        public int cutMarker1Index = -1;
        public int cutMarker2Index = -1;
    }

    public enum MultiCutStatus {Moving, Cutting, AllCutsFinished};
    private MultiCutStatus taskStatus = MultiCutStatus.Moving;
    
    private List<CutData> cutData;
    private List<GameObject> cutMarkers;
    private bool badCut = false;
    private int cutStartedStep = -1;
    private Vector3 cutStartedToolPosition = new Vector3(0f, 0f, 0f);

    private Dictionary<int, int> cutOrderToRopeIndexMap = new Dictionary<int, int>();
    private Dictionary<int, int> markerLocationMap = new Dictionary<int, int>();
    public int numRopesCut = 0;

    private Vector3 originalPosition;
    private Quaternion originalRotation;
    private Vector3 originalCutMarkerScale;
    
    public override void Initialize()
    {
        base.Initialize();

        originalPosition = RopeInstance.transform.position;
        originalRotation = RopeInstance.transform.rotation;

        CutDetector = Solver.GetComponent<MultiCutDetector>();
        CutDetector.Agent = this;
        cutMarkers = new List<GameObject>();

        if (multiCutVariant == MultiCutVariant.ThreeRopes)
        {
            for (int i = 0; i < 6; i++)
            {
                cutMarkers.Add(Instantiate(CutMarkerPrefab, ParentScene.transform));
            }
            cutOrderToRopeIndexMap = new Dictionary<int, int>
            {
                {0, 0},
                {1, 1},
                {2, 2},
            };
        }
        if (multiCutVariant == MultiCutVariant.MeshStraight)
        {
            ObiRope[] ropes = RopeInstance.GetComponentsInChildren<ObiRope>();
            foreach (ObiRope rope in ropes)
            {
                if (rope.transform.name == "hrope")
                {
                    cutMarkers.Add(Instantiate(CutMarkerPrefab, ParentScene.transform));
                    cutMarkers.Add(Instantiate(CutMarkerPrefab, ParentScene.transform));
                }
            }

            cutOrderToRopeIndexMap = new Dictionary<int, int>
            {
                {0, 0},              
                {1, 1},
                {2, 2},   
                {3, 3},
                {4, 4},
                {5, 5}
            };
        }
        originalCutMarkerScale = CutMarkerPrefab.transform.localScale;
    }


    public void LateUpdate()
    {
        UpdateCutMarkerPosition();
    }

    public override void EpisodeReset()
    {
        ResetFloor();
        ResetLight();
        ResetCamera();
        
        ResetRope();
        ResetToolColor();
        Vector3 toolSpawnPos = new Vector3(
            0.0f,
            0.9f,
            1.77f);
        ResetTool(0, toolSpawnPos, new Vector3(0, 90, 90));
        taskStatus = MultiCutStatus.Moving;
        cutStartedStep = -1;
        numRopesCut = 0;
        badCut = false;
        
        cutData = new List<CutData>();
        int cutmarkerIndex = 0;
        // Set goal element index of each rope
        // There will be one cutData per actor (rope), and the indexing of
        // the actors will be used by CutDetectedCallback
        if (multiCutVariant == MultiCutVariant.ThreeRopes)
        {
            for (int i = 0; i < Solver.actors.Count; i++)
            {
                if (Solver.actors[i] is ObiTearableCloth) continue;
                int numElements = ((ObiRope)Solver.actors[i]).elements.Count;
                CutData data = new CutData
                {
                    solverIndex = i,
                    goalElementIndex = Random.Range(
                    4, numElements - 4)
                };
                data.cutMarker1Index = cutmarkerIndex;
                data.cutMarker2Index = cutmarkerIndex + 1;
                cutmarkerIndex += 2;
                cutData.Add(data);
            }
        }
        else if (multiCutVariant == MultiCutVariant.MeshStraight)
        {
            // Temp code for setting goal in 6 x 6 grid
            int goal = Random.Range(0, 5);
            goal = 2;
            int goalElement = goal * 3 + 1;
            for (int i = 0; i < Solver.actors.Count; i++)
            {
                if (Solver.actors[i] is ObiTearableCloth) continue;
                CutData data = new CutData();
                data.solverIndex = i;
                
                if (Solver.actors[i].transform.name == "hrope")
                {
                    int numElements = ((ObiRope)Solver.actors[i]).elements.Count;
                    data.goalElementIndex = goalElement;
                    data.cutMarker1Index = cutmarkerIndex;
                    data.cutMarker2Index = cutmarkerIndex + 1;
                    cutmarkerIndex += 2;
                }
                cutData.Add(data);
            }
        }
    }

    private void ResetRope()
    {
        DestroyImmediate(RopeInstance);
        
        RopeInstance = (GameObject)Instantiate(
            RopePrefab, originalPosition, originalRotation, Solver.gameObject.transform);


        int toolMask = 1 << 1;
        var toolFilter = ObiUtils.MakeFilter(toolMask, 2);
        
        Renderer ropeRenderer = Solver.actors[0].GetComponent<Renderer>();
        float newRopeColor = DomainRandomizer.Instance.RandomizeDomain(
                ropeRenderer.material.color.r, "rope_r");
        Color ropeColor = new Color(newRopeColor, newRopeColor, newRopeColor);

        Vector2 ropeTiling = new Vector2(
            DomainRandomizer.Instance.RandomizeDomain(
                ropeRenderer.material.mainTextureScale.x,
                "x_tiling"),
            DomainRandomizer.Instance.RandomizeDomain(
                ropeRenderer.material.mainTextureScale.y,
                "y_tiling"));

        for (int i = 0; i < Solver.actors.Count; i++)
        {
            if (Solver.actors[i] is ObiRope)
            {
                ObiRope rope = Solver.actors[i] as ObiRope;
                float thickness = DomainRandomizer.Instance.RandomizeDomain(
                    rope.solver.principalRadii[0].x, "rope_thickness");

                for (int j = 0; j < rope.solverIndices.count; j++)
                {
                    int solverIndex = rope.solverIndices[j];
                    rope.solver.principalRadii[solverIndex] = new Vector4(
                        thickness, thickness, thickness);
                }

                Renderer renderer = rope.transform.GetComponent<Renderer>();
                if (renderer != null)
                {
                    rope.GetComponent<Renderer>().material.color = ropeColor;
                    rope.GetComponent<Renderer>().material.mainTextureScale = ropeTiling;
                }
            }
            else if (Solver.actors[i] is ObiTearableCloth)
            {
                ObiTearableCloth cloth = Solver.actors[i] as ObiTearableCloth;

                List<System.Tuple<int, int>> tearablePairs = new List<System.Tuple<int, int>>()
                {
                    new System.Tuple<int, int>(132, 249),
                    new System.Tuple<int, int>(251, 131),
                    new System.Tuple<int, int>(154, 155),
                    new System.Tuple<int, int>(163, 162),
                };
                List<StructuralConstraint> tornEdges = new List<StructuralConstraint>();
                
                var dc = cloth.GetConstraintsByType(Oni.ConstraintType.Distance) as ObiConstraints<ObiDistanceConstraintsBatch>;

                for (int batchIndex = 0; batchIndex < dc.batches.Count; ++batchIndex)
                {
                    var batch = dc.batches[batchIndex] as ObiDistanceConstraintsBatch;
                    for (int constraintIndex = 0; constraintIndex < batch.activeConstraintCount; constraintIndex++)
                    {
                        Vector3 particlePosition1 = cloth.GetParticlePosition(cloth.solverIndices[batch.particleIndices[constraintIndex * 2]]);
                        Vector3 particlePosition2 = cloth.GetParticlePosition(cloth.solverIndices[batch.particleIndices[constraintIndex * 2 + 1]]);
                        //Debug.Log("Particle " + batch.particleIndices[constraintIndex * 2] + " position: " + particlePosition1 + "Particle " + batch.particleIndices[constraintIndex * 2 + 1] + " position: " + particlePosition2);

                        if (particlePosition1.z == particlePosition2.z)
                        {
                            if ((particlePosition1.x < 0 && particlePosition1.x> -0.04f) && (particlePosition2.x > 0 && particlePosition2.x < 0.05f))
                            {
                                if (particlePosition1.z > 1f)
                                {
                                    Debug.Log("Tearable pair: " + batch.particleIndices[constraintIndex * 2] + ", " + batch.particleIndices[constraintIndex * 2 + 1] + " at " + particlePosition1.x + ", " + particlePosition2.x);
                                    cloth.Tear(new StructuralConstraint(batch, constraintIndex, 1));
                                }
                            }
                            else if ((particlePosition1.x > 0 && particlePosition1.x < 0.05f) && (particlePosition2.x < 0 && particlePosition2.x > -0.04f))
                            {
                                if (particlePosition1.z > 1f)
                                {
                                    Debug.Log("Tearable pair: " + batch.particleIndices[constraintIndex * 2] + ", " + batch.particleIndices[constraintIndex * 2 + 1] + " at " + particlePosition1.x + ", " + particlePosition2.x);
                                    cloth.Tear(new StructuralConstraint(batch, constraintIndex, 1));
                                }
                            }

                        }
                        // System.Tuple<int, int> pair = new System.Tuple<int, int>(batch.particleIndices[constraintIndex * 2], batch.particleIndices[constraintIndex * 2 + 1]);
                        // if (tearablePairs.Contains(pair))
                        // {
                        //     cloth.Tear(new StructuralConstraint(batch, constraintIndex, 100000));
                        // }
                    }
                }

                // cloth.UpdateDeformableTriangles();
            }
        }

        float mult = 0.75f;
        if (multiCutVariant == MultiCutVariant.ThreeRopes) mult = 0.92f;

        float markerScaling =  Solver.principalRadii[0].x / 0.02f * mult;
        Vector3 cutMarkerScale = new Vector3(
            originalCutMarkerScale .x * markerScaling,
            originalCutMarkerScale.y,
            originalCutMarkerScale.z * markerScaling);
        
        float particleDistance = Vector3.Distance(
            Solver.actors[0].GetParticlePosition(0),
            Solver.actors[0].GetParticlePosition(1)) / 2;
        if (multiCutVariant == MultiCutVariant.MeshStraight)
        {
            // cutMarkerScale.y *= Random.Range(0.4f, 1.2f);
            cutMarkerScale.y = particleDistance * 1.2f;
        }
        else {
            cutMarkerScale.y = particleDistance * 1.2f;
        }

        Color newMarkerColor = DomainRandomizer.Instance.RandomizeColor(
            cutMarkers[0].GetComponent<Renderer>().material.color,
            "marker_r", "marker_g", "marker_b");

        foreach (GameObject marker in cutMarkers)
        {
            marker.transform.localScale = cutMarkerScale;
            Renderer renderer = marker.GetComponent<Renderer>();
            renderer.material.color = newMarkerColor;
        }

        ObiCollider[] toolColliders = Arms[0].RootObject.GetComponentsInChildren<ObiCollider>();
        for (int i = 0; i < toolColliders.Length; i++)
        {
            toolColliders[i].Filter = toolFilter;
        }
    }

    private void UpdateCutMarkerPosition()
    {
        for (int i = 0; i < cutData.Count; i++)
        {
            if (cutData[i].goalElementIndex == -1) continue;
            ObiRope rope = Solver.actors[cutData[i].solverIndex] as ObiRope;
            if (!cutData[i].isCut)
            {
                AlignCutMarker(
                    cutMarkers[cutData[i].cutMarker1Index].transform,
                    rope.GetParticlePosition(rope.elements[cutData[i].goalElementIndex].particle1),
                    rope.GetParticlePosition(rope.elements[cutData[i].goalElementIndex].particle2),
                    false);
                AlignCutMarker(
                    cutMarkers[cutData[i].cutMarker2Index].transform,
                    rope.GetParticlePosition(rope.elements[cutData[i].goalElementIndex].particle1),
                    rope.GetParticlePosition(rope.elements[cutData[i].goalElementIndex].particle2),
                    false);
            }
            else
            {
                AlignCutMarker(
                    cutMarkers[cutData[i].cutMarker1Index].transform,
                    rope.GetParticlePosition(rope.elements[cutData[i].goalElementIndex].particle2),
                    rope.GetParticlePosition(rope.elements[cutData[i].goalElementIndex].particle1),
                    true);
                AlignCutMarker(
                    cutMarkers[cutData[i].cutMarker2Index].transform,
                    rope.GetParticlePosition(rope.elements[cutData[i].goalElementIndex - 1].particle1),
                    rope.GetParticlePosition(rope.elements[cutData[i].goalElementIndex - 1].particle2),
                    true);
            }
        }
    }

    private void AlignCutMarker(Transform objTransform, Vector3 pointA, Vector3 pointB, bool isCut)
    {
        Vector3 halfwayPoint = pointA + ((pointB - pointA) / 2f);
        if (isCut)
        {
            halfwayPoint = halfwayPoint + ((pointB - halfwayPoint) / 2f);
        }
        objTransform.position = halfwayPoint;

        Vector3 dir = pointB - pointA;
        objTransform.rotation = Quaternion.LookRotation(dir);
        objTransform.localRotation *= Quaternion.Euler(-90, 0, 0);
    }


    public override void CollectObservations(VectorSensor sensor)
    {
    }

    public void CutDetectedCallback(
        int cutElementIndex, ObiActor actor, CutQuality quality)
    {
        if (cutData[Solver.actors.IndexOf(actor)].isCut) return;

        // If the goal element is not set, this rope was not meant to be cut
        if (cutData[Solver.actors.IndexOf(actor)].goalElementIndex == -1)
        {
            badCut = true;
            return;
        }

        // if (cutData[Solver.actors.IndexOf(actor)].goalElementIndex != cutElementIndex)
        // {
        //     badCut = true;
        //     return;
        // }

        Transform markerTransform = cutMarkers[cutData[Solver.actors.IndexOf(actor)].cutMarker1Index].transform;
        Vector3 cylinderRight = markerTransform.transform.position + (new Vector3(1, 0, 0) * markerTransform.transform.localScale.y);
        Vector3 cylinderLeft = markerTransform.transform.position + (new Vector3(-1, 0, 0) * markerTransform.transform.localScale.y);

        if (ToolMidpoint.transform.position.x <= cylinderLeft.x || ToolMidpoint.transform.position.x >= cylinderRight.x)
        {
            badCut = true;
            return;
        }
        
        if (cutData[Solver.actors.IndexOf(actor)].goalElementIndex != cutElementIndex)
        {
            badCut = true;
            return;
        }

        // Fail if there is a rope before this rope that is not cut
        if (cutOrderToRopeIndexMap[numRopesCut] != Solver.actors.IndexOf(actor))
        {
            badCut = true;
            return;
        }
        numRopesCut++;

        cutData[Solver.actors.IndexOf(actor)].isCut = true;
        cutData[Solver.actors.IndexOf(actor)].quality = quality;

        int marker1Index = cutData[Solver.actors.IndexOf(actor)].cutMarker1Index;
        int marker2Index = cutData[Solver.actors.IndexOf(actor)].cutMarker2Index;
        
        Vector3 scale = cutMarkers[marker1Index].transform.localScale;
        scale.y = scale.y / 2f;
        cutMarkers[marker1Index].transform.localScale = scale;

        scale = cutMarkers[marker2Index].transform.localScale;
        scale.y = scale.y / 2f;
        cutMarkers[marker2Index].transform.localScale = scale;

        // Record the positions and step to check for successful cut behaviour
        taskStatus = MultiCutStatus.Cutting;
        cutStartedToolPosition = ToolMidpoint.transform.position;
        cutStartedStep = StepCount;

        if (rewardMode != RewardMode.Sparse) return;
        AddReward(2f);
        reward += 2f;
    }

    public override void CheckEndConditions()
    {
        base.CheckEndConditions();

        if (CheckCutStartedEndConitions()) return;
        if (CheckTaskEndCondition()) return;
        if (CheckCutFinishedEndConitions()) return;
    }

    public bool CheckCutStartedEndConitions()
    {
        // This avoid a null reference exception from causing episode reset
        // within the callback function related to obi rigidbody updates
        if (badCut)
        {
            TaskFailure(-1.0f);
            return true;
        }
        return false;
    }

    public bool CheckCutFinishedEndConitions()
    {
        if (taskStatus != MultiCutStatus.Cutting) return false;

        // Use time and distance to determine if the cut is successful 
        if ((StepCount - cutStartedStep) > 30) 
        {
            TaskFailure(-1.0f);
            return true;
        }
        else if (Vector3.Distance(
            ToolMidpoint.transform.position, cutStartedToolPosition) > 0.1)
        {
            TaskFailure(-1.0f);
            return true;
        }
        else if (Arms[0].controller.GetJawAngleDegrees() < 1)
        {
            bool allCut = true;
            foreach (CutData data in cutData)
            {
                if (data.goalElementIndex == -1) continue;
                if (!data.isCut)
                {
                    allCut = false;
                    break;
                }
            }
            if (allCut) taskStatus = MultiCutStatus.AllCutsFinished;
            else taskStatus = MultiCutStatus.Moving;
            
            if (rewardMode != RewardMode.Sparse) return false;
            AddReward(2f);
            reward += 2f;
        }

        return false;
    }

    public bool CheckTaskEndCondition()
    {
        if (taskStatus != MultiCutStatus.AllCutsFinished) return false;

        if (Vector3.Distance(
            ToolMidpoint.transform.position, Goal.transform.position) < 0.1)
        {
            TaskComplete(2.0f);
            return true;
        }

        return false;
    }

    public override void UpdateReward()
    {
        if (rewardMode == RewardMode.Sparse)
        {
            base.UpdateReward();
            return;
        }

        float negStepReward = -(float)StepCount / (float)MaxStep;
        float distanceProgress = 0f;
        float goalProgress = 0f;
        float sparseCutReward = 0f;

        if (taskStatus != MultiCutStatus.AllCutsFinished && numRopesCut < cutOrderToRopeIndexMap.Count)
        {
            int ropeIndex = cutOrderToRopeIndexMap[numRopesCut];
            for (int i = 0; i < cutData.Count; i++)
            {
                if (cutData[i].solverIndex == ropeIndex)
                {
                    ObiRope rope = Solver.actors[cutData[i].solverIndex] as ObiRope;
                    distanceProgress = AgentHelper.ExpDistanceReward(
                        ToolMidpoint.transform.position,
                        rope.GetParticlePosition(
                            rope.elements[cutData[i].goalElementIndex].particle1),
                        0.05f, 100f, 4.0f);
                    break;
                }
            }
        }
        else
        {
            goalProgress = Vector3.Distance(
                ToolMidpoint.transform.position, Goal.transform.position);
            goalProgress = AgentHelper.ExpDistanceReward(
                ToolMidpoint.transform.position,
                Goal.transform.position,
                0.05f, 100f, 4.0f);
        }

        // Add old distance progresses from previous ropes
        for (int i = 0; i < cutData.Count; i++)
        {
            if (cutData[i].goalElementIndex == -1) continue;
            if (cutData[i].isCut)
            {
                distanceProgress += 1f;
                sparseCutReward += 2f;
            }
        }

        float current_reward = negStepReward + distanceProgress + 
            sparseCutReward + goalProgress;
        AddReward(current_reward - reward);
        reward = current_reward;
    }

    public override void Heuristic(in ActionBuffers actionsOut)
    {
        if (Arms[0].controller.Controller == RobotController.ControllerType.Primitive)
        {
            var continuousActionsOut = actionsOut.ContinuousActions;
            var discreteActionsOut = actionsOut.DiscreteActions;

            discreteActionsOut[0] = 1;

            if (Input.GetAxis("Horizontal") > 0)
            {
                continuousActionsOut[0] = 1f;
                continuousActionsOut[1] = 1f;
            }
            else if (Input.GetAxis("Horizontal") < 0)
            {
                continuousActionsOut[0] = -1f;
                continuousActionsOut[1] = 1f;
            }
            else if (Input.GetAxis("Vertical") < 0)
            {
                continuousActionsOut[0] = 0f;
                continuousActionsOut[1] = 1f;
            }
            else if (Input.GetAxis("Vertical") > 0)
            {
                continuousActionsOut[0] = 0f;
                continuousActionsOut[1] = -1f;
            }
        }
        else
        {
            AddInputToActionBuffers(actionsOut, Input.GetAxis("Horizontal"), "position_x");
            AddInputToActionBuffers(actionsOut, Input.GetAxis("AltVertical"), "position_y");
            AddInputToActionBuffers(actionsOut, Input.GetAxis("Vertical"), "position_z");
            AddInputToActionBuffers(actionsOut, Input.GetAxis("UpDown"), "rotation_y");
            AddInputToActionBuffers(actionsOut, Arms[0].jawOpen ? 1f : -1f, "jaw");
        }
    }
}
