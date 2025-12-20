using UnityEngine;
using Mujoco;

public class MjPushBlockAgent : PushBlockAgent
{
    public override void Initialize()
    {
        InitializeAgent();
    }

    public override void EpisodeReset()
    {
        ResetFloor();
        ResetLight();
        ResetCamera();
        ResetMjGoal();
        ResetMjBlock();
        ResetArm(0, ParentScene.transform.position + new Vector3(0f, 0.0125f, 0.0885f), new Vector3(0, -90, 180));
    }

    public bool MjCheckBlockSpawnPos(Vector3 pos)
    {
        if (Vector3.Distance(pos, Goal.transform.position) < .0725f)
        {
            return false;
        }
        return true;
    }

    public unsafe void ResetMjBlock()
    {
        Vector3 position = GetRandomSpawnPos(
            Block,
            new Vector2(-areaBounds.extents.x, areaBounds.extents.x),
            new Vector2(-areaBounds.extents.z, areaBounds.extents.z),
            MjCheckBlockSpawnPos);
        position.y = Block.transform.position.y * Block.transform.localScale.x;

        Quaternion rotation = Quaternion.Euler(0.0f, Random.Range(0f, 90f), 0.0f);

        int qid = Block.GetComponentInChildren<MjBaseJoint>().QposAddress;

        MjEngineTool.SetMjTransform(&MjScene.Instance.Data->qpos[qid], position, rotation);
        MjEngineTool.SetMjTransform(&MjScene.Instance.Data->qvel[qid], Vector3.zero, Quaternion.identity);

        // Block.GetComponentInChildren<MjGeom>().Mass = DomainRandomizer.Instance.RandomizeDomain(
        //     Block.GetComponentInChildren<MjGeom>().Mass, "mass");

        // float scale = DomainRandomizer.Instance.RandomizeDomain(
        //     Block.transform.localScale.x, "scale");
        // Block.transform.localScale = new Vector3(scale, scale, scale);

        Color newBlockColor = DomainRandomizer.Instance.RandomizeColor(
            Block.GetComponentInChildren<Renderer>().material.color,
            "block_r", "block_g", "block_b");
        Block.GetComponentInChildren<Renderer>().material.color = newBlockColor;

        blockStartPosition = position;
    }

    public void ResetMjGoal()
    {
        Color newGoalColor = DomainRandomizer.Instance.RandomizeColor(
            Goal.GetComponent<Renderer>().material.color,
            "target_r", "target_g", "target_b");
        Goal.GetComponent<Renderer>().material.color = newGoalColor;
    }

    public bool CheckGoal()
    {
        if (Version == PushBlockVersion.V1)
        {
            return Mathf.Abs(Block.transform.position.z - Goal.transform.position.z) < 0.03f;
        }
        return false;
    }

    public override void CheckEndConditions()
    {
        if (CheckGoal())
        {
            TaskComplete(2.0f);
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
            4.0f);

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
}

