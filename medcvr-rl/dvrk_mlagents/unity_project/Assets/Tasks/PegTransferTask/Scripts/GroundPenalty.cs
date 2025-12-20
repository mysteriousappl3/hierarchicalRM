using UnityEngine;

public class GroundPenalty : MonoBehaviour
{
    public PegTransferAgent Agent;
    private float softPenalty = -0.005f;

    private void OnCollisionStay(Collision other)
    {
        if (other.collider.gameObject.layer != LayerMask.NameToLayer("OuterBlockEdge") &&
            other.collider.gameObject.layer != LayerMask.NameToLayer("InnerBlockEdge"))
        {
            Agent.AddPenalty(softPenalty);
        }
    }
}
