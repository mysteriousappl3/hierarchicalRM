using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class CollisionStayDetect : MonoBehaviour
{
    // This is set automatically as the Agent already has a reference to the block
    [HideInInspector]
    public DepthReachTargetAgent Agent;
    private void OnCollisionStay(Collision other)
    {
        Agent.AddBoundaryPenalty();
    }
}
