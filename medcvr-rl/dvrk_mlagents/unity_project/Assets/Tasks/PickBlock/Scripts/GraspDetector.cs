using System.Collections;
using System.Collections.Generic;
using UnityEngine;

// This script must be placed on the block
public class GraspDetector : MonoBehaviour
{
    
    // This is set automatically as the Agent already has a reference to the block
    [HideInInspector]
    public PickBlockAgent Agent;

    private List<Collider> colliders = new List<Collider>();

    // Both the jaws are trigger colliders, so we only look for triggers here
    private void OnTriggerEnter(Collider other)
    {
        if (!other.CompareTag("jaw")) { return; }
        if (!colliders.Contains(other)) { colliders.Add(other); }

        if (colliders.Count > 1) {
            Agent.AddGraspReward();
        }
    }

    private void OnTriggerExit(Collider other)
    {
        colliders.Remove(other);
        Agent.RemoveGraspReward();
    }
}
