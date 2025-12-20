using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class GoalPenaltyTrigger : MonoBehaviour
{
    // This is set automatically as the Agent already has a reference to the block
    // [HideInInspector]
    public RALRollBlockAgent Agent;

    private void OnTriggerEnter(Collider other)
    {
        if (other.CompareTag("Goal"))
        {
            Agent.HitAGoal();
        }
    }
}
