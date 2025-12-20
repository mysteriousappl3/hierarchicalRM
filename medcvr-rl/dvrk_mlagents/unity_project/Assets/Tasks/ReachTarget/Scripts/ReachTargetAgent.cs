using System.Collections.Generic;
using UnityEngine;
using Unity.MLAgents;
using Unity.MLAgents.Sensors;
using Unity.MLAgents.Actuators;
using System.IO;

public class ReachTargetAgent : BaseAgent
{
    [Header("Reach Target References")]
    // Task Specific Environment References
    // See Parent for generic references
    public GameObject Goal;

    public override void EpisodeReset()
    {
        base.EpisodeReset();
        ResetGoal();
    }

    public override void CheckEndConditions()
    {
        CheckInsideGoal();
    }

    public void CheckInsideGoal()
    {
        Vector3 projTip = new Vector3(ToolTip.transform.position.x, 0, ToolTip.transform.position.z);
        Vector3 projGoal = new Vector3(Goal.transform.position.x, 0, Goal.transform.position.z);

        if (Vector3.Distance(projTip, projGoal) < 0.5)
        {
            AddReward(1.0f);
            reward += 1.0f;
            ResetGoal();
        }
    }

    void ResetGoal()
    {
        Goal.transform.position = GetRandomSpawnPos(
            Goal,
            new Vector2(-areaBounds.extents.x, areaBounds.extents.x),
            new Vector2(-areaBounds.extents.z, areaBounds.extents.z));
        int randomRot = Random.Range(0, 90);
        Goal.transform.rotation = Quaternion.Euler(0, randomRot, 0);

        float scale = DomainRandomizer.Instance.RandomizeDomain(Goal.transform.localScale.x, "scale");
        Goal.transform.localScale = new Vector3(scale, scale, scale);

        Goal.GetComponent<Renderer>().material.color = DomainRandomizer.Instance.RandomizeColor(
            Goal.GetComponent<Renderer>().material.color, "goal_r", "goal_g", "goal_b");
    }

    public override void Heuristic(in ActionBuffers actionsOut)
    {
        AddInputToActionBuffers(actionsOut, Input.GetAxis("Horizontal"), "position_x");
        AddInputToActionBuffers(actionsOut, Input.GetAxis("Vertical"), "position_z");
    }
}

