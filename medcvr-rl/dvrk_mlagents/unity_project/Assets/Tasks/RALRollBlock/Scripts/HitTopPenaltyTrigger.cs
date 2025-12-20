using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class HitTopPenaltyTrigger : MonoBehaviour
{
    // This is set automatically as the Agent already has a reference to the block
    [HideInInspector]
    public RALRollBlockAgent Agent;

    private void OnCollisionEnter(Collision other)
    {
        if (other.collider.CompareTag("lnd_gripper_link_0") && !Agent.isToolLeftofBlock)
        {
            // Debug.Log("Added Boundary Penalty for hitting tol of block");
            Agent.AddBoundaryPenalty();
        }
    }
}
