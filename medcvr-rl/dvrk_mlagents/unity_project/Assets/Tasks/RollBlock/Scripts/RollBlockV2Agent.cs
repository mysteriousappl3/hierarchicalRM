using UnityEngine;
using Unity.MLAgents.Actuators;
using System.Collections.Generic;

public class RollBlockV2Agent : BaseAgent
{
    [Header("Roll Block References and Settings")]
    public GameObject Block;
    public GameObject Goal;
    public enum RewardMode { Sparse, Dense }
    public RewardMode rewardMode = RewardMode.Sparse;

    public float RollProgressRewardScale = 0.5f;
    public float DistanceRewardScaling = 0.5f;
    public float HomeDistanceRewardScaling = 0.5f;

    private bool rollFinished = false;

    private Rigidbody blockBody;
    private Vector3 blockStartingPosition;

    public override void Initialize()
    {
        base.Initialize();
        blockBody = Block.GetComponent<Rigidbody>();
    }

    public override void EpisodeReset()
    {
        base.EpisodeReset();
        ResetBlock();
        ResetPsmTipBehindBlock();
        rollFinished = false;
        Goal.transform.localPosition = new Vector3(0f, 4 * -Block.transform.localScale.z, Block.transform.localScale.y);
    }

    void ResetBlock()
    {
        float scale = DomainRandomizer.Instance.RandomizeDomain(Block.transform.localScale.x, "scale");
        Block.transform.localScale = new Vector3(scale, scale, scale);

        Block.transform.position = GetRandomSpawnPos(
            Block,
            new Vector2(-areaBounds.extents.x, areaBounds.extents.x),
            new Vector2(-areaBounds.extents.z, areaBounds.extents.z));

        Debug.Log("Block position: " + Block.transform.position.ToString());

        blockStartingPosition = Block.transform.localPosition;

        Block.transform.rotation = new Quaternion();
        float euler_y = DomainRandomizer.Instance.RandomizeDomain(Block.transform.localEulerAngles.y, "block_euler_y");
        Block.transform.localEulerAngles = new Vector3(0.0f, 180 + Random.Range(-euler_y, euler_y), 0.0f);

        blockBody.mass = DomainRandomizer.Instance.RandomizeDomain(blockBody.mass, "mass");
        blockBody.linearVelocity = Vector3.zero;
        blockBody.angularVelocity = Vector3.zero;

        var blockCollider = Block.GetComponent<Collider>();
        var block_friction = DomainRandomizer.Instance.RandomizeDomain(blockCollider.material.dynamicFriction, "block_friction");
        blockCollider.material.dynamicFriction = block_friction;
        blockCollider.material.staticFriction = block_friction;

        Block.GetComponent<Renderer>().material.color = DomainRandomizer.Instance.RandomizeColor(
            Block.GetComponent<Renderer>().material.color,
            "block_r", "block_g", "block_b");
    }

    void ResetPsmTipBehindBlock()
    {
        // Vector3 tip_position_wrt_world = Block.transform.position;
        // tip_position_wrt_world.y += Block.transform.localScale.y/2;
        // tip_position_wrt_world.z += 2 * Block.transform.localScale.z;

        // tip_position_wrt_world.x += DomainRandomizer.Instance.RandomizeDomain(0.0f, "tool_position_noise_x");
        // tip_position_wrt_world.y += DomainRandomizer.Instance.RandomizeDomain(0.0f, "tool_position_noise_y");
        // tip_position_wrt_world.z += DomainRandomizer.Instance.RandomizeDomain(0.0f, "tool_position_noise_z");

        // ResetPSMandTip(0, tip_position_wrt_world);
        ResetArm(0);
    }

    public override void CheckEndConditions()
    {
        CheckSlideTooFar();
        CheckTaskComplete();
        CheckSuccessfulRoll();
    }

    public void CheckSuccessfulRoll()
    {
        if (!rollFinished)
        {
            if (Block.transform.localEulerAngles.x > 85f && Block.transform.localEulerAngles.x < 95)
            {
                rollFinished = true;
                if (rewardMode != RewardMode.Dense) return;
                AddReward(1.0f);
                reward += 1.0f;
            }
        }
    }

    public void CheckTaskComplete()
    {
        if (rollFinished)
        {
            if (Vector3.Distance(ToolTip.transform.position, Goal.transform.position) < 0.1f)
            {
                AddReward(2.0f);
                reward += 2.0f;
                EndEpisode();
            }
        }
    }

    public void CheckSlideTooFar()
    {   
        if (Vector3.Distance(Block.transform.localPosition, blockStartingPosition) > 1.0f)
        {
            AddReward(-2.0f);
            reward -= 2.0f;
            EndEpisode();
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

                float distanceProgress = 0.0f;
                float rollProgress = 0.0f;
                float homeProgress;

                if (!rollFinished)
                {
                    float blockDistance = Vector3.Distance(
                        ToolTip.transform.position,
                        Block.transform.position);
                    blockDistance = blockDistance - (Block.transform.localScale.y * 0.8f);
                    blockDistance = Mathf.Clamp(blockDistance, 0.0f, 100.0f);
                    distanceProgress = Mathf.Exp(-blockDistance);

                    float rollAngle = Block.transform.localEulerAngles.x;
                    if (rollAngle > 90) rollAngle = rollAngle - 360;
                    Mathf.Clamp(rollAngle, 0, 90.0f);
                    rollProgress = rollAngle / 90f;

                    // Ignore the small deviations in roll angle when sliding
                    if (Mathf.Abs(rollProgress) < 0.05f) rollProgress = 0.0f;
                    homeProgress = 0.0f;
                }
                else
                {
                    rollProgress = 1.0f;
                    distanceProgress = 1.0f;
                    // For homing we move to the left of the block, this allows
                    // for multiple rolls in real world
                    homeProgress = Vector3.Distance(
                        ToolTip.transform.position, Goal.transform.position);
                    homeProgress = Mathf.Exp(-homeProgress);
                }

                distanceProgress *= DistanceRewardScaling;
                rollProgress *= RollProgressRewardScale;
                homeProgress *= HomeDistanceRewardScaling;

                float current_reward = negStepReward + distanceProgress + rollProgress + (rollFinished ? 2.0f : 0.0f) + homeProgress;
                AddReward(current_reward - reward);
                reward = current_reward;
                break;
        }
    }

    public override void Heuristic(in ActionBuffers actionsOut)
    {
        AddInputToActionBuffers(actionsOut, -Input.GetAxis("Horizontal"), "position_z");
        AddInputToActionBuffers(actionsOut, Input.GetAxis("Vertical"), "position_y");
        AddInputToActionBuffers(actionsOut, Input.GetAxis("UpDown"), "position_x");
    }
}
