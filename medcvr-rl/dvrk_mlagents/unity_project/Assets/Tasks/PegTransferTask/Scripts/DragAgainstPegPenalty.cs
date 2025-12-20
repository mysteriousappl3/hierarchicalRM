using UnityEngine;

public class DragAgainstPegPenalty : MonoBehaviour
{
    public PegTransferAgent Agent;

    private float collisionStartTime;
    public float softPenalty;
    private float penaltyDuration;

    private void Start()
    {
        softPenalty = -0.005f;
        penaltyDuration = 5f;
    }

    void OnCollisionEnter(Collision other)
    {
        if (other.collider.gameObject.layer == LayerMask.NameToLayer("OuterBlockEdge") ||
            other.collider.gameObject.layer == LayerMask.NameToLayer("InnerBlockEdge") ||
            (other.collider.gameObject.layer == LayerMask.NameToLayer("RobotTool")) ||
            (other.collider.name == "tool_gripper1_link") ||
            (other.collider.name == "tool_gripper2_link"))
        {
            collisionStartTime = Time.time;
        }
    }

    private void OnCollisionStay(Collision other)
    {
        if (other.collider.gameObject.layer == LayerMask.NameToLayer("OuterBlockEdge") ||
            other.collider.gameObject.layer == LayerMask.NameToLayer("InnerBlockEdge") ||
            (other.collider.gameObject.layer == LayerMask.NameToLayer("RobotTool")) ||
            (other.collider.name == "tool_gripper1_link") ||
            (other.collider.name == "tool_gripper2_link"))
        {
            float collisionTime = Time.time - collisionStartTime;
            
            if (collisionTime >= penaltyDuration)
            {
                Agent.AddPenalty(softPenalty);
            }
        }
    }
}
