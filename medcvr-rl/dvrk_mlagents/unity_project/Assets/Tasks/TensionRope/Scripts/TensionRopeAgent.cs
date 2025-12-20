using UnityEngine;
using UnityEditor;
using Unity.MLAgents.Actuators;
using Obi;
using System.Collections;

public class TensionRopeAgent : BaseAgent
{
    [Header("Tension Rope References")]
    // Task Specific Environment References
    // See Parent for generic references
    public ObiSolver Solver;
    public GameObject RopeInstance;
    public GameObject RopePrefab;
    public GameObject ToolMidpoint;

    enum TensionRopeVariants { TwoDimensions, ThreeDimensions };
    [Header("Tension Rope Settings")]
    [SerializeField] TensionRopeVariants Mode;
    public enum RewardMode { Sparse, Dense }
    public RewardMode rewardMode = RewardMode.Sparse;
    public float GraspDistanceRewardScaling = 1.0f;
    public float TensionRewardScaling = 1.0f;

    public float TensionThreshold = 0.02f;
    public float DesiredTension = 1.15f;

    private ObiRope rope;
    private Vector3 originalRopePosition;
    private Quaternion originalRopeRotation;
    private RopeGraspDetector ropeGraspDetector;
    public enum TensionRopeStatus { Grasping, Tensioning, Tensioned };
    private TensionRopeStatus taskStatus = TensionRopeStatus.Grasping;
    private System.Collections.Generic.List<int> graspGoalElementIndexRange;
    private int tensionedStartStep = 0;

    public override void Initialize()
    {
        base.Initialize();

        originalRopePosition = RopeInstance.transform.position;
        originalRopeRotation = RopeInstance.transform.rotation;

        ropeGraspDetector = Solver.GetComponent<RopeGraspDetector>();
        ropeGraspDetector.Agent = this;
        EpisodeReset();
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

    public override void EpisodeReset()
    {
        ResetFloor();
        ResetLight();
        ResetCamera();
        StartCoroutine(ResetRope());
        ResetTool(0, new Vector3(0.0f, 1.2f, 1.77f), new Vector3(0, 90, 180));
        ResetToolColor();

        CollisionDetect[] collisionDetectors = 
            RopeInstance.GetComponentsInChildren<CollisionDetect>();
        foreach (CollisionDetect collisionDetector in collisionDetectors)
        {
            collisionDetector.Agent = this;
        }

        taskStatus = TensionRopeStatus.Grasping;
        tensionedStartStep = 0;
        ropeGraspDetector.GraspDetected = false;
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

        graspGoalElementIndexRange = new System.Collections.Generic.List<int> {
            rope.elements.Count - 3, rope.elements.Count - 1};
    }

    public void GraspDetectedCallback(int graspElementIndex)
    {
        if (taskStatus != TensionRopeStatus.Grasping) return;

        if (graspElementIndex < graspGoalElementIndexRange[0] 
            || graspElementIndex > graspGoalElementIndexRange[1])
        {
            TaskFailure(-2.0f);
            return;
        }
        if (graspElementIndex == rope.elements.Count - 1)
        {
            // Avoid grasps too close to the tip of the rope
            if (Vector3.Distance(
                    ToolMidpoint.transform.position,
                    rope.GetParticlePosition(
                        rope.elements[graspElementIndex].particle2)) < 0.05f)
            {
                TaskFailure(-2.0f);
                return;
            }
        }

        taskStatus = TensionRopeStatus.Tensioning;
        Arms[0].controller.SetMinJawAngleRadians(
            Arms[0].controller.GetJawAngleRadians());
    }

    public void GraspNotDetectedCallback()
    {
        taskStatus = TensionRopeStatus.Grasping;
        Arms[0].controller.SetMinJawAngleRadians(0.0f);
    }

    public override void PenaltyTriggerCallback() 
    {
        TaskFailure(-2.0f);
    }

    public override void CheckEndConditions()
    {
        UpdateRopeTensionState();
        CheckGraspAngle();
    }

    public void UpdateRopeTensionState()
    {
        if (taskStatus == TensionRopeStatus.Grasping) return;

        Vector3 lastParticlePosition = rope.GetParticlePosition(
            rope.elements[graspGoalElementIndexRange[0]].particle1);

        Vector3 desiredParticleLocation = CalculateTensionedRopeLocation();

        if (Vector3.Distance(
            lastParticlePosition, desiredParticleLocation) < TensionThreshold)
        {
            taskStatus = TensionRopeStatus.Tensioned;
            if (tensionedStartStep == 0)
            {
                tensionedStartStep = StepCount;
            }
        }
        else
        {
            taskStatus = TensionRopeStatus.Tensioning;
            tensionedStartStep = 0;
        }
    }

    public void CheckGraspAngle()
    {
        if (taskStatus == TensionRopeStatus.Grasping) return;

        if (ToolMidpoint.transform.rotation.eulerAngles.z > 270f)
        {
            TaskFailure(-2.0f);
            return;
        }
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
        float sparseGraspReward = 0f;
        float sparseTensionReward = 0f;

        if (taskStatus == TensionRopeStatus.Grasping)
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
                ToolMidpoint.transform.position, goalPoint, 0.025f, 100f, 4.0f);
        }
        else if (taskStatus == TensionRopeStatus.Tensioning)
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
        else
        {
            graspProgress = 1.0f;
            tensionProgress = 1.0f;
            sparseTensionReward = 2.0f;
        }

        graspProgress *= GraspDistanceRewardScaling;
        tensionProgress *= TensionRewardScaling;

        // Discourage oscillations after grasping by encouraging the jaw to be
        // desired shut when the rope is grasped
        if (taskStatus != TensionRopeStatus.Grasping && Arms[0].controller.GetJointCommand("jaw") < 0.25f)
        {
            sparseGraspReward = 2.0f;
        }

        float current_reward = negStepReward + sparseGraspReward +
            sparseTensionReward + graspProgress + tensionProgress;

        // Debug.Log(" Reward: " + reward +
        //           " NegStep: " + negStepReward +
        //           " Current: " + current_reward +
        //           " Grasp: " + graspProgress +
        //           " Tension: " + tensionProgress +
        //           " SparseGrasp: " + sparseGraspReward + 
        //           " SparseTension: " + sparseTensionReward);
        AddReward(current_reward - reward);
        reward = current_reward;
    }

    public override void Heuristic(in ActionBuffers actionsOut)
    {
        AddInputToActionBuffers(actionsOut, Input.GetAxis("Horizontal"), "position_x");
        AddInputToActionBuffers(actionsOut, Input.GetAxis("Vertical"), "position_y");
        AddInputToActionBuffers(actionsOut, Arms[0].jawOpen ? 1f : -1f, "jaw");
        AddInputToActionBuffers(actionsOut, Input.GetAxis("UpDown"), "rotation_z");
    }
}
