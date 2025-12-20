using UnityEngine;
using Unity.MLAgents;
using Unity.MLAgents.Sensors;
using Unity.MLAgents.Actuators;

public class PickBlockAgent : BaseAgent
{
    [Header("Pick Block References and Settings")]
    // Task Specific Environment References
    // See Parent for generic references
    public GameObject Block;
    public GameObject Goal;
    public GameObject ToolMidpoint;

    public enum PickBlockVariants { TwoDimensions, ThreeDimensions };
    public PickBlockVariants Mode = PickBlockVariants.TwoDimensions;

    public enum RewardMode { Sparse, Dense }
    public RewardMode rewardMode = RewardMode.Sparse;
    public float GraspDistanceRewardScaling = 1.0f;
    public float PickDistanceRewardScaling = 1.0f;

    private Rigidbody blockBody;
    private Vector3 originalBlockPosition;
    private Vector3 startBlockPosition;
    //Note: Don't forget to reset sparse reward triggers
    private bool graspRewardAdded = false;

    [HideInInspector]
    public GraspDetector GraspDetect;

    public override void Initialize()
    {
        base.Initialize();

        blockBody = Block.GetComponent<Rigidbody>();
        GraspDetect = Block.GetComponent<GraspDetector>();
        GraspDetect.Agent = this;

        originalBlockPosition = Block.transform.localPosition;

        // // Special fix for bad unity physics
        // var gripper = transform.Find("world/base_link/yaw_link/pitch_back_link/pitch_bottom_link/pitch_end_link/tool_mount_link/main_insertion_link/tool_roll_link/tool_pitch_link/tool_yaw_link/tool_gripper2_link").GetComponent<ArticulationBody>();
        // ArticulationDrive currentDrive = gripper.xDrive;
        // currentDrive.forceLimit = 1;
        // gripper.xDrive = currentDrive;

        // gripper = transform.Find("world/base_link/yaw_link/pitch_back_link/pitch_bottom_link/pitch_end_link/tool_mount_link/main_insertion_link/tool_roll_link/tool_pitch_link/tool_yaw_link/tool_gripper1_link").GetComponent<ArticulationBody>();
        // currentDrive = gripper.xDrive;
        // currentDrive.forceLimit = 1;
        // gripper.xDrive = currentDrive;

        // blockBody.solverIterations = 30;
        // blockBody.solverVelocityIterations = 30;

        EpisodeReset();
    }

    public override void EpisodeReset()
    {
        graspRewardAdded = false;
        base.EpisodeReset();
        ResetBlock();
    }

    void ResetBlock()
    {

        Vector2 xExtents = new Vector2(-areaBounds.extents.x, areaBounds.extents.x);
        Vector2 zExtents = new Vector2(-areaBounds.extents.z, areaBounds.extents.z);
        if (Mode == PickBlockVariants.TwoDimensions)
            zExtents = new Vector2(originalBlockPosition.z, originalBlockPosition.z);

        Block.transform.position = GetRandomSpawnPos(
            Block,
            xExtents,
            zExtents);

        startBlockPosition = Block.transform.position;

        Block.transform.localEulerAngles = new Vector3(0.0f, 0.0f, 0.0f);
        blockBody.linearVelocity = Vector3.zero;
        blockBody.angularVelocity = Vector3.zero;

        Block.GetComponent<Renderer>().material.color = DomainRandomizer.Instance.RandomizeColor(
            Block.GetComponent<Renderer>().material.color,
            "block_r", "block_g", "block_b");

        blockBody.mass = DomainRandomizer.Instance.RandomizeDomain(blockBody.mass, "mass");
        float scale = DomainRandomizer.Instance.RandomizeDomain(Block.transform.localScale.x, "scale");
        Block.transform.localScale = new Vector3(scale, scale, scale);
    }


    public override void CollectObservations(VectorSensor sensor)
    {
        if (UseVectorObservation)
        {
            // Object locations in environment space (6)
            //sensor.AddObservation(ToolMidpoint.transform.position - ParentScene.transform.position);
            //sensor.AddObservation(Block.transform.position - ParentScene.transform.position);
            // Relative position of block from tip (3)
            sensor.AddObservation(Block.transform.position - ToolMidpoint.transform.position);

            // This variation of pick block only cares about lifting the block, therefore y only (2)
            sensor.AddObservation(Goal.transform.position.y - Block.transform.position.y);
            sensor.AddObservation(Goal.transform.position.y - ToolMidpoint.transform.position.y);

            // Jaw angle to know if jaw is currently open/close (1)
            sensor.AddObservation(System.Convert.ToSingle(Arms[0].controller.GetJawAngleRadians()));
            //Total (12)
        }
    }

    public void AddGraspReward()
    {
        if (!graspRewardAdded)
        {
            graspRewardAdded = true;
            if (rewardMode == RewardMode.Dense) return;
            AddReward(1.0f);
            reward += 1.0f;
        }
    }

    public void RemoveGraspReward()
    {
        if (graspRewardAdded)
        {
            graspRewardAdded = false;
            if (rewardMode == RewardMode.Dense) return;
            AddReward(-1.0f);
            reward -= 1.0f;
        }
    }

    public override void CheckEndConditions()
    {
        base.CheckEndConditions();
        CheckBlockFallen();
        CheckTaskComplete();
    }

    public void CheckBlockFallen()
    {
        if (Block.transform.position.y < Ground.transform.position.y)
        {
            AddReward(-1.0f);
            reward -= 1.0f;
            EndEpisode();
        }
    }

    public void CheckTaskComplete()
    {
        if (graspRewardAdded)
        {
            if (Vector3.Distance(Block.transform.position, Goal.transform.position) < 0.1)
            {
                AddReward(2.0f);
                reward += 2.0f;
                EndEpisode();
            }
        }
    }

    public override void UpdateReward()
    {
        switch (rewardMode)
        {
            case RewardMode.Sparse:
                base.UpdateReward();
                break;
            case RewardMode.Dense:
                float negStepReward = -(float)StepCount / (float)MaxStep;
                negStepReward = 0f;
                float graspProgress = 0f;
                float pickProgress = 0f;
                if (!graspRewardAdded)
                {
                    graspProgress = Vector3.Distance(
                        ToolMidpoint.transform.position,
                        Block.transform.position);
                    // Clip distance when close to block
                    graspProgress = graspProgress - (Block.transform.localScale.y * 0.9f);
                    graspProgress = Mathf.Clamp(graspProgress, 0.0f, 100f);

                    graspProgress = Mathf.Exp(-graspProgress);
                    pickProgress = 0f;
                }
                else
                {
                    graspProgress = 1.0f;

                    float startingDistance = Vector3.Distance(
                        startBlockPosition,
                        Goal.transform.position);

                    float pickDistance = Vector3.Distance(
                        Block.transform.position,
                        Goal.transform.position);

                    pickProgress = 1 - (pickDistance / startingDistance);
                }

                graspProgress *= GraspDistanceRewardScaling;
                pickProgress *= PickDistanceRewardScaling;
                
                float sparseGraspReward = 0.0f;
                // Discourage oscillations by encouraging the jaw to be desired shut when the block is grasped
                if (graspRewardAdded && Arms[0].controller.GetJointCommand("jaw") < 0.1f)
                {
                    sparseGraspReward = 2.0f;
                }

                float current_reward = negStepReward + 
                    graspProgress + pickProgress + sparseGraspReward;
                
                AddReward(current_reward - reward);
                reward = current_reward;
                break;
            default:
                break;
        }
    }

    public override void Heuristic(in ActionBuffers actionsOut)
    {
        AddInputToActionBuffers(actionsOut, Input.GetAxis("Horizontal"), "position_x");
        AddInputToActionBuffers(actionsOut, Input.GetAxis("Vertical"), "position_y");
        AddInputToActionBuffers(actionsOut, Arms[0].jawOpen ? 1f : -1f, "jaw");
    }
}
