using UnityEngine;
using UnityEditor;
using Unity.MLAgents.Sensors;
using Unity.MLAgents.Actuators;
using Obi;
using System;
using System.Security;
using Unity.MLAgents;
using System.Collections;
using System.Linq;

public class TensionCutRopeAgent : BaseAgent
{
    [Header("Tension Rope References")]
    // Task Specific Environment References
    // See Parent for generic references
    public ObiSolver Solver;
    public GameObject RopeInstance;
    public GameObject RopePrefab;
    public GameObject LNDToolMidpoint;
    public GameObject RTSToolMidpoint;
    public GameObject HomingGoal;

    enum TensionRopeVariants { TwoDimensions, ThreeDimensions };
    [Header("Tension Rope Settings")]
    [SerializeField] TensionRopeVariants Mode;
    public enum RewardMode { Sparse, Dense }
    public RewardMode rewardMode = RewardMode.Sparse;

    public float GraspDistanceRewardScaling = 1.0f;
    public float TensionRewardScaling = 1.0f;
    public float CutDistanceRewardScaling = 1.0f;
    public float HomeDistanceRewardScaling = 1.0f;

    private ObiRope rope;
    private Vector3 originalRopePosition;
    private Quaternion originalRopeRotation;
    private TensionCutDetector tensionCutDetector;
    public enum TensionStatus { Grasping, Tensioning, Tensioned };
    private TensionStatus tensionTaskStatus = TensionStatus.Grasping;
    public enum CuttingStatus {Stationairy, Cutting, CutStarted, CutFinished};
    private CuttingStatus cuttingTaskStatus = CuttingStatus.Stationairy;

    // Tension Related Variables
    private System.Collections.Generic.List<int> graspGoalElementIndexRange;
    public float TensionThreshold = 0.02f;
    public float DesiredTension = 1.15f;
    private int tensionedStartStep = 0;

    // Cutting Related Variables
    private int cutStartedStep = -1;
    private Vector3 cutStartedToolPosition = new Vector3(0f, 0f, 0f);
    private System.Collections.Generic.List<int> cutGoalElementIndexRange;
    private Vector3 RTSStartPosition;
    private Vector3 cutLocation;
    public enum CutQuality { Bad, Good, Best };
    private CutQuality cutQuality = CutQuality.Bad;

    public override void Initialize()
    {
        base.Initialize();

        originalRopePosition = RopeInstance.transform.position;
        originalRopeRotation = RopeInstance.transform.rotation;

        tensionCutDetector = Solver.GetComponent<TensionCutDetector>();
        tensionCutDetector.Agent = this;
    }

#if UNITY_EDITOR
    [ContextMenu("SaveBpState")]
    void SaveBpState()
    {
        var passThisOne = Instantiate<ObiActorBlueprint>(rope.blueprint);
        rope.SaveStateToBlueprint(passThisOne);
        AssetDatabase.CreateAsset(passThisOne, "Assets/SavedRopeState.asset");
    }
#endif

    protected override void Update()
    {
        // By default, space will open the jaw of only the first arm
        if (Input.GetKeyDown(KeyCode.Space))
        {
            Arms[0].jawOpen = !Arms[0].jawOpen;
        }
        else if (Input.GetKeyDown(KeyCode.LeftShift))
        {
            Arms[1].jawOpen = !Arms[1].jawOpen;
        }
    }

    public override void EpisodeReset()
    {
        ResetFloor();
        ResetLight();
        ResetCamera();
        StartCoroutine(ResetRope());

        ResetTool(0, new Vector3(0.25f, 1.3f, 2.12f), new Vector3(0, 90, 180));
        ResetTool(1, new Vector3(-0.25f, 1.3f, 2.12f), new Vector3(0, 90, 180));

        Arms[0].controller.SetMinJawAngleRadians(0.0f);

        CollisionDetect[] collisionDetectors = 
            RopeInstance.GetComponentsInChildren<CollisionDetect>();
        foreach (CollisionDetect collisionDetector in collisionDetectors)
        {
            collisionDetector.Agent = this;
        }

        tensionCutDetector.CutDetected = false;
        tensionCutDetector.GraspDetected = false;

        cutStartedStep = -1;
        tensionedStartStep = 0;

        tensionTaskStatus = TensionStatus.Grasping;
        cuttingTaskStatus = CuttingStatus.Stationairy;

        // The goal is to grasp the rope at the end
        graspGoalElementIndexRange = new System.Collections.Generic.List<int>{
            rope.elements.Count - 3, rope.elements.Count - 1};
        cutGoalElementIndexRange = new System.Collections.Generic.List<int>{6, 7};
    }

    private IEnumerator ResetRope()
    {
        rope = RopeInstance.GetComponent<ObiRope>();
        rope.RemoveFromSolver();

        rope.ClearState();
        rope.AddToSolver();

        while (!rope.isLoaded)
            yield return new WaitForEndOfFrame();

        rope.stretchingScale = DomainRandomizer.Instance.RandomizeDomain(
            rope.stretchingScale, "rope_sag");
        float thickness = DomainRandomizer.Instance.RandomizeDomain(
            rope.solver.principalRadii[0].x, "rope_thickness");

        for (int i = 0; i < rope.solverIndices.count; i++)
        {
            int solverIndex = rope.solverIndices[i];
            rope.solver.principalRadii[solverIndex] = new Vector3(
                thickness, thickness, thickness);
        }

        tensionCutDetector.UnpinRope();
    }

    public void GraspDetectedCallback(int graspElementIndex)
    {
        if (tensionTaskStatus != TensionStatus.Grasping) return;

        if (graspElementIndex < graspGoalElementIndexRange[0] 
            || graspElementIndex > graspGoalElementIndexRange[1])
        {
            TaskFailure(-1.0f);
            return;
        }

        // Avoid grasps too close to the tip of the rope
        if (graspElementIndex == rope.elements.Count - 1)
        {
            if (Vector3.Distance(
                    LNDToolMidpoint.transform.position,
                    rope.GetParticlePosition(
                        rope.elements[graspElementIndex].particle2)) < 0.05f)
            {
                TaskFailure(-1.0f);
                return;
            }
        }

        tensionTaskStatus = TensionStatus.Tensioning;
        Arms[0].controller.SetMinJawAngleRadians(
            Arms[0].controller.GetJawAngleRadians());
    }

    public void GraspNotDetectedCallback()
    {
        tensionTaskStatus = TensionStatus.Grasping;
        Arms[0].controller.SetMinJawAngleRadians(0.0f);
    }

    public void CutDetectedCallback(int cutElementIndex, CutQuality quality)
    {
        // if (cutElementIndex < cutGoalElementIndexRange[0] 
        //     || cutElementIndex > cutGoalElementIndexRange[1])
        // {
        //     TaskFailure(-1.0f);
        //     return;
        // }

        cutQuality = quality;
        cuttingTaskStatus = CuttingStatus.CutStarted;
        cutStartedToolPosition = RTSToolMidpoint.transform.position;
        cutStartedStep = StepCount;
    }

    public override void PenaltyTriggerCallback()
    {
        TaskFailure(-2.0f);
    }

    public override void CheckEndConditions()
    {
        UpdateRopeTension();
        CheckTaskComplete();
        // CheckSuccessfulCut();
        // CheckRTSStationairy();
        // CheckGraspAngle();
        // CheckRopeIsGrasped();
    }

    public Vector3 CalculateTensionedRopeLocation()
    {
        Vector3 firstParticlePosition = rope.GetParticlePosition(
                rope.elements[0].particle1);

        float restLength = rope.restLength * 
            graspGoalElementIndexRange[0] / rope.elements.Count;
        float tensionedLength = restLength * DesiredTension;            
        float desiredXPosition = firstParticlePosition.x + tensionedLength;

        return new Vector3(
            desiredXPosition,
            firstParticlePosition.y,
            firstParticlePosition.z);
    }

    public void UpdateRopeTension()
    {
        if (tensionTaskStatus == TensionStatus.Grasping) return;

        Vector3 lastParticlePosition = rope.GetParticlePosition(
            rope.elements[graspGoalElementIndexRange[0]].particle1);

        Vector3 desiredParticleLocation = CalculateTensionedRopeLocation();

        if (Vector3.Distance(
            lastParticlePosition, desiredParticleLocation) < TensionThreshold)
        {
            tensionTaskStatus = TensionStatus.Tensioned;
            if (cuttingTaskStatus == CuttingStatus.Stationairy)
                cuttingTaskStatus = CuttingStatus.Cutting;
            if (tensionedStartStep == 0)
            {
                tensionedStartStep = StepCount;
            }
        }
        else
        {
            tensionTaskStatus = TensionStatus.Tensioning;
            tensionedStartStep = 0;
        }
    }

    public void CheckSuccessfulCut()
    {
        if (cuttingTaskStatus != CuttingStatus.CutStarted) return;

        // Depends on the jaw speed, but 30 steps should be enough to close
        if ((StepCount - cutStartedStep) > 30)
        {
            Debug.Log("Took too long");
            TaskFailure(-1.0f);
        }
        else if (Vector3.Distance(
                RTSToolMidpoint.transform.position,
                cutStartedToolPosition) > 0.05)
        {
            Debug.Log("Moved too far");
            TaskFailure(-1.0f);
        }
        else if (Arms[1].controller.GetJawAngleDegrees() < 0.1)
        {
            cuttingTaskStatus = CuttingStatus.CutFinished;
            cutLocation = RTSToolMidpoint.transform.position;
        }
    }

    public void CheckTaskComplete()
    {
        if (cuttingTaskStatus != CuttingStatus.CutFinished) return;
        if (Vector3.Distance(
                    RTSToolMidpoint.transform.position,
                    HomingGoal.transform.position) < 0.1)
            {
                Debug.Log("Task Complete");
                TaskComplete(2.0f);
            }
    }

    public void CheckGraspAngle()
    {
        if (tensionTaskStatus == TensionStatus.Grasping) return;

        if (LNDToolMidpoint.transform.rotation.eulerAngles.z > 270f)
        {
            TaskFailure(-2.0f);
            return;
        }
    }

    public void CheckRTSStationairy()
    {
        // RTS must stay stationairy while in the tensioning phase
        if (cuttingTaskStatus != CuttingStatus.Stationairy) return;

        if (StepCount < 2) RTSStartPosition = RTSToolMidpoint.transform.position;
        else

        if (Vector3.Distance(
                RTSToolMidpoint.transform.position,
                RTSStartPosition) > 0.05)
        {
            TaskFailure(-1.0f);
        }
    }

    public void CheckRopeIsGrasped()
    {
        // Once the cut is done we don't care about the 
        if (cuttingTaskStatus == CuttingStatus.CutFinished) return;
        
        // Rope must be tensioned once we start cutting
        if (cuttingTaskStatus != CuttingStatus.Stationairy
            && tensionTaskStatus == TensionStatus.Grasping)
        {
            TaskFailure(-1.0f);
        }
    }

    public override void UpdateReward()
    {
        if (rewardMode == RewardMode.Sparse)
        {
            base.UpdateReward();
            return;
        }

        float negStepReward = -(float)StepCount / (float)MaxStep;

        float graspProgress = 0f;
        float tensionProgress = 0f;
        float cutProgress = 0.0f;
        float homeProgress = 0.0f;
        float sparseGraspReward = 0f;
        float sparseTensionReward = 0f;
        float sparseCutReward = 0.0f;

        if (tensionTaskStatus == TensionStatus.Grasping)
        {
            int middleElement = (
                graspGoalElementIndexRange[0] + graspGoalElementIndexRange[1]) / 2;

            Vector3 firstParticlePosition = rope.GetParticlePosition(
                rope.elements[middleElement].particle1);
            Vector3 secondParticlePosition = rope.GetParticlePosition(
                rope.elements[middleElement].particle2);
            Vector3 goalPoint = (
                firstParticlePosition + secondParticlePosition) / 2f;

            graspProgress = AgentHelper.ExpDistanceReward(
                LNDToolMidpoint.transform.position, goalPoint, 0.025f, 100f, 4.0f);
        }
        else if (tensionTaskStatus == TensionStatus.Tensioning)
        {
            graspProgress = 1.0f;

            Vector3 lastParticlePosition = rope.GetParticlePosition(
                rope.elements[graspGoalElementIndexRange[0]].particle1);

            Vector3 desiredParticleLocation = CalculateTensionedRopeLocation();

            tensionProgress = AgentHelper.ExpDistanceReward(
                lastParticlePosition,
                desiredParticleLocation,
                TensionThreshold, 100f, 4.0f);
        }
        else if (tensionTaskStatus == TensionStatus.Tensioned
                 && cuttingTaskStatus == CuttingStatus.Cutting)
        {
            graspProgress = 1.0f;
            tensionProgress = 1.0f;

            int middleElement = (
                cutGoalElementIndexRange[0] + cutGoalElementIndexRange[1]) / 2;

            Vector3 firstParticlePosition = rope.GetParticlePosition(
                rope.elements[middleElement].particle1);
            Vector3 secondParticlePosition = rope.GetParticlePosition(
                rope.elements[middleElement].particle2);
            Vector3 goalPoint = (
                firstParticlePosition + secondParticlePosition) / 2f;

            cutProgress = AgentHelper.ExpDistanceReward(
                RTSToolMidpoint.transform.position, goalPoint, 0.025f, 100f, 4.0f);

            // Keep track of cut marker location to use for homing
            cutLocation = RTSToolMidpoint.transform.position;
        }
        else
        {
            graspProgress = 1.0f;
            tensionProgress = 1.0f;
            cutProgress = 1.0f;
            // For homing, we move towards the center of the goal collider based on linear distance from ground to goal
            homeProgress = Vector3.Distance(
                RTSToolMidpoint.transform.position,
                HomingGoal.transform.position);
            homeProgress = 1 - (homeProgress / 
                Vector3.Distance(HomingGoal.transform.position, cutLocation));
        }


        graspProgress *= GraspDistanceRewardScaling;
        tensionProgress *= TensionRewardScaling;
        cutProgress *= CutDistanceRewardScaling;
        homeProgress *= HomeDistanceRewardScaling;

        // Discourage oscillations after grasping by encouraging the jaw to be
        // desired shut when the rope is grasped
        if (tensionTaskStatus != TensionStatus.Grasping && Arms[0].controller.GetJointCommand("jaw") < 0.25f)
        {
            sparseGraspReward = 2.0f;
        }

        if (tensionTaskStatus == TensionStatus.Tensioned)
        {
            sparseTensionReward = 2.0f;
        }

        
        if (cuttingTaskStatus == CuttingStatus.CutStarted)
        {
            sparseCutReward = 1.0f;
        }
        else if (cuttingTaskStatus == CuttingStatus.CutFinished)
        {
            sparseCutReward = 2.0f;
        }
        
        switch (cutQuality)
        {
            case CutQuality.Bad:
                break;
            case CutQuality.Good:
                sparseCutReward *= 2;
                break;
            case CutQuality.Best:
                sparseCutReward *= 4;
                break;
            default:
                break;
        }
    

        float current_reward = negStepReward + sparseGraspReward +
            sparseTensionReward + graspProgress + tensionProgress + 
            sparseCutReward + cutProgress + homeProgress;

        // Debug.Log(" Current: " + current_reward +
        //           " Grasp: " + graspProgress +
        //           " Tension: " + tensionProgress +
        //           " SparseGrasp: " + sparseGraspReward + 
        //           " SparseTension: " + sparseTensionReward + 
        //           " Cut: " + cutProgress +
        //           " SparseCut: " + sparseCutReward +
        //           " Home: " + homeProgress);
        AddReward(current_reward - reward);
        reward = current_reward;
    }

    public override void Heuristic(in ActionBuffers actionsOut)
    {
        AddInputToActionBuffers(actionsOut, Input.GetAxis("Horizontal"), "psm1_position_x");
        AddInputToActionBuffers(actionsOut, Input.GetAxis("Vertical"), "psm1_position_y");
        AddInputToActionBuffers(actionsOut, Input.GetAxis("UpDown"), "psm1_rotation_z");
        AddInputToActionBuffers(actionsOut, Arms[0].jawOpen ? 1f : -1f, "psm1_jaw");
        AddInputToActionBuffers(actionsOut, Input.GetAxis("AltHorizontal"), "psm2_position_x");
        AddInputToActionBuffers(actionsOut, Input.GetAxis("AltVertical"), "psm2_position_y");
        AddInputToActionBuffers(actionsOut, Arms[1].jawOpen ? 1f : -1f, "psm2_jaw");
    }
}
