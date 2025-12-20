using UnityEngine;

public class EscapedStartPeg : MonoBehaviour
{
    public PegTransferAgent Agent;

    private void OnTriggerExit(Collider other)
    {
        Transform blockTransform = Agent.GetBlockTransform();
        if (blockTransform.position.y >= Agent.goalPosition.y)
        {
            Agent.EscapePegReward();
        }
    }
}
