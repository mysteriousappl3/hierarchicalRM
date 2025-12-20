using UnityEngine;
using Unity.MLAgents.Sensors;
using Unity.MLAgents.Actuators;

public class PushBlockAgent : BaseAgent
{
    [Header("Push Block References and Settings")]
    // Task Specific Environment References
    // See Parent for generic references
    public GameObject Goal;
    public GameObject Block;
    public enum PushBlockVersion { V1, V2 }
    public PushBlockVersion Version = PushBlockVersion.V1;

    public enum RewardMode { Sparse, Dense }
    public RewardMode rewardMode = RewardMode.Sparse;

    public float ToolDistanceRewardScaling = 1.0f;
    public float GoalDistanceRewardScaling = 2.0f;

    [HideInInspector]
    public GoalTrigger goalDetect;
    protected Rigidbody blockBody;
    protected Vector3 blockStartPosition;


    public override void Initialize()
    {
        InitializeAgent();
        blockBody = Block.GetComponent<Rigidbody>();
        goalDetect = Block.GetComponent<GoalTrigger>();
        goalDetect.Agent = this;
    }

    public override void EpisodeReset()
    {
        base.EpisodeReset();
        ResetGoal();
        ResetBlock();
        ResetArm(0, ParentScene.transform.position + new Vector3(0, 0.25f, 1.77f), new Vector3(0, 180f, 180f));
    }

    public bool CheckBlockSpawnPos(Vector3 pos)
    {
        if (Vector3.Distance(pos, Goal.transform.position) < 1.5f)
        {
            return false;
        }
        return true;
    }

    public void ResetBlock()
    {
        Block.transform.position = GetRandomSpawnPos(
            Block,
            new Vector2(-areaBounds.extents.x, areaBounds.extents.x),
            new Vector2(-areaBounds.extents.z, areaBounds.extents.z),
            CheckBlockSpawnPos);

        Block.transform.localEulerAngles = new Vector3(0.0f, Random.Range(0f, 90f), 0.0f);

        blockBody.linearVelocity = Vector3.zero;
        blockBody.angularVelocity = Vector3.zero;

        blockBody.mass = DomainRandomizer.Instance.RandomizeDomain(
            blockBody.mass, "mass");
        float scale = DomainRandomizer.Instance.RandomizeDomain(
            Block.transform.localScale.x, "scale");
        Block.transform.localScale = new Vector3(scale, scale, scale);

        Color newBlockColor = DomainRandomizer.Instance.RandomizeColor(
            Block.GetComponent<Renderer>().material.color,
            "block_r", "block_g", "block_b");
        Block.GetComponent<Renderer>().material.color = newBlockColor;

        blockStartPosition = Block.transform.position;
    }

    public void ResetGoal()
    {
        Color newGoalColor = DomainRandomizer.Instance.RandomizeColor(
            Goal.GetComponent<Renderer>().material.color,
            "target_r", "target_g", "target_b");
        Goal.GetComponent<Renderer>().material.color = newGoalColor;

        if (Version == PushBlockVersion.V2)
        {
            Goal.transform.position = GetRandomSpawnPos(
                Goal,
                new Vector2(-areaBounds.extents.x, areaBounds.extents.x),
                new Vector2(-areaBounds.extents.z, areaBounds.extents.z));

            float scale = DomainRandomizer.Instance.RandomizeDomain(
                Goal.transform.localScale.x, "goal_scale");
            Goal.transform.localScale = new Vector3(scale, 0.1f, scale);

            Goal.transform.localEulerAngles = new Vector3(0.0f, Random.Range(0f, 90f), 0.0f);
        }
    }

    public override void GoalTriggerCallback()
    {
        TaskComplete(2.0f);
    }

    public override void CollectObservations(VectorSensor sensor)
    {
        if (UseVectorObservation)
        {
            sensor.AddObservation(Goal.transform.position - ToolTip.transform.position);
            sensor.AddObservation(Block.transform.position - ToolTip.transform.position);
            sensor.AddObservation(Block.transform.position - Goal.transform.position);
            //Total (9)
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
        float goalProgress = 0;

        float toolProgress = AgentHelper.ExpDistanceReward(
            ToolTip.transform.position,
            Block.transform.position,
            Block.transform.position.y,
            100.0f,
            1.0f);

        if (Version == PushBlockVersion.V1)
        {
            goalProgress = Mathf.Abs(
                Block.transform.position.z - Goal.transform.position.z);
            goalProgress = 1 - (
                goalProgress / Mathf.Abs(Goal.transform.position.z - blockStartPosition.z));
        }
        else if (Version == PushBlockVersion.V2)
        {
            goalProgress = Vector3.Distance(
                Block.transform.position, Goal.transform.position);
            goalProgress = 1 - (
                goalProgress / Vector3.Distance(Goal.transform.position, blockStartPosition));
        }

        goalProgress *= GoalDistanceRewardScaling;
        toolProgress *= ToolDistanceRewardScaling;

        float current_reward = goalProgress + toolProgress + negStepReward;
        AddReward(current_reward - reward);
        reward = current_reward;
    }

    public override void Heuristic(in ActionBuffers actionsOut)
    {
        AddInputToActionBuffers(actionsOut, Input.GetAxis("Horizontal"), "position_x");
        AddInputToActionBuffers(actionsOut, Input.GetAxis("Vertical"), "position_z");
    }
}

