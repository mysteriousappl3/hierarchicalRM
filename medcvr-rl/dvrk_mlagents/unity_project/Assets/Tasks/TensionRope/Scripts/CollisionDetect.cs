using UnityEngine;

public class CollisionDetect : MonoBehaviour
{
    [HideInInspector]
    public BaseAgent Agent;

    private void OnCollisionEnter(Collision other)
    {
        // Since the rope doesn't have a regular collider detection,
        // we know that any collision with the mount is a collision with the tool
        Debug.Log("Collision detected with " + other.gameObject.name);
        Agent.PenaltyTriggerCallback();
    }
}
