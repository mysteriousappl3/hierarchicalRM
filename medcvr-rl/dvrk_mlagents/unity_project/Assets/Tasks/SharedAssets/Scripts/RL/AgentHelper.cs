using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using Unity.MLAgents;

public static class AgentHelper
{
    public static float ExpDistanceReward(
        Vector3 currentPos,
        Vector3 targetPos,
        float tolerance,
        float maxDistance,
        float expMultiplier,
        float rounding = 1000f)
        {
            float distance = Vector3.Distance(currentPos, targetPos);
            distance -= tolerance;
            distance = Mathf.Clamp(distance, 0.0f, maxDistance);
            float reward = Mathf.Exp(-expMultiplier * distance);
            reward = Mathf.Round(reward * rounding) / rounding;
            return reward;
        }
    
    public static float ExpDistanceReward(
        float currentPos,
        float targetPos,
        float tolerance,
        float maxDistance,
        float expMultiplier)
        {
            float distance = Mathf.Abs(currentPos - targetPos);
            distance -= tolerance;
            distance = Mathf.Clamp(distance, 0.0f, maxDistance);
            float reward = Mathf.Exp(-expMultiplier * distance);
            return reward;
        }
}
