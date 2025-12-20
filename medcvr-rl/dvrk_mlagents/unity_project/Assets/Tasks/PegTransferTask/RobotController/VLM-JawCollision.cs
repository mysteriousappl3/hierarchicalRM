
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Assertions;

public class VLMJawCollision : MonoBehaviour
{
    private GameObject robot;
    [SerializeField]
    private UrdfJointController controller;
    public Dictionary<string, UrdfJointMapping> jointNameToActiveJoint;

    public bool isColliding;
    public VLMJawCollision otherJaw;
    public bool objectGrabbed;
    public bool pickedBlockOnce = false;    // Tracks if agent has picked the block at least once or not

    public int edgeLayer;   // Default = 0, Inner edge collider = 1, Outer edge collider = 2

    public PegTransferAgent agent;

    public LowLevelMotor motor;

    private Transform topMostParent;

    public enum BehaviourMode { RL, API }
    public BehaviourMode behaviourMode = BehaviourMode.RL;

    public bool GRAB_BLOCK_ENABLED = true;

    public void Start()
    {
        topMostParent = GetTopMostParent(transform);
        isColliding = false;
        objectGrabbed = false;
        edgeLayer = 0;
        robot = GameObject.FindWithTag("robot");

        if (robot != null)
        {
            controller = robot.GetComponent<UrdfJointController>();
            jointNameToActiveJoint = controller.GetJointMapping();
        }

        if (behaviourMode == BehaviourMode.RL)
        {
            GRAB_BLOCK_ENABLED = true;
        }

    }


    Transform GetTopMostParent(Transform child)
    {
        // Traverse up the hierarchy until we reach the root
        while (child.parent != null)
        {
            child = child.parent;
        }
        return child; // Return the top-most parent
    }

    private GameObject FindChildWithTag(Transform parent, string tag)
    {
        if (parent.CompareTag(tag))
        {
            return parent.gameObject;
        }

        foreach (Transform child in parent)
        {
            GameObject foundChild = FindChildWithTag(child, tag);
            if (foundChild != null)
            {
                return foundChild;
            }
        }
        return null;
    }

    private void OnCollisionStay(Collision collision)
    {
        if (!GRAB_BLOCK_ENABLED)
        {
            return;
        }

        if (!controller.GetJawOpen())
        {
            if (collision.collider.gameObject.layer == LayerMask.NameToLayer("InnerBlockEdge"))
            {
                edgeLayer = 1;
            }
            else if (collision.collider.gameObject.layer == LayerMask.NameToLayer("OuterBlockEdge"))
            {
                edgeLayer = 2;
            }
            else
            {
                edgeLayer = 0;
                return;
            }

            if ((edgeLayer == 1 || edgeLayer == 2) &&
                (otherJaw.edgeLayer == 1 || otherJaw.edgeLayer == 2) &&
                (edgeLayer != otherJaw.edgeLayer))
            {
                pickedBlockOnce = true;
                isColliding = true;
                objectGrabbed = true;

                // Remove the rigid body component from it
                if (behaviourMode == BehaviourMode.API)
                {
                    // Use the motor.currHoop
                    //Assert.IsNotNull(motor.currHoop);

                    if (motor.currHoop == null)
                    {
                        // Reset set variables
                        edgeLayer = 0;
                        otherJaw.edgeLayer = 0;
                        pickedBlockOnce = false;
                        otherJaw.pickedBlockOnce = false;
                        isColliding = false;
                        otherJaw.isColliding = false;
                        objectGrabbed = false;
                        otherJaw.objectGrabbed = false;
                        return;
                    }

                    GameObject block = motor.currHoop;
                    Rigidbody rb = block.GetComponent<Rigidbody>();
                    if (rb != null)
                    {
                        // Debug.Log("[API] Removing RigidBody");
                        Destroy(rb);
                    }
                    GameObject tooltip = GameObject.Find("tool_midpoint");
                    block.transform.SetParent(tooltip.transform);
                }
                else
                {
                    GameObject block = GameObject.FindWithTag("Block");
                    Rigidbody rb = block.GetComponent<Rigidbody>();
                    if (rb != null)
                    {
                        // Debug.Log("Removing RigidBody");
                        Destroy(rb);
                    }
                    GameObject tooltip = GameObject.Find("tool_midpoint");
                    block.transform.SetParent(tooltip.transform);
                }

                controller.isCollisionDetected = true;

                float contactAngle = float.MaxValue;
                ContactPoint[] collisionContacts = new ContactPoint[collision.contactCount];
                collision.GetContacts(collisionContacts);
                foreach (ContactPoint contact in collisionContacts)
                {

                    Vector3 normal = contact.normal;
                    // Calculate the angle between the normal of jaw's collider surface and the X-axis
                    float angle = CalculateAngleWithXAxis(normal);
                    if (angle < contactAngle)
                    {
                        contactAngle = angle;
                    }
                }
                // Jaw triggered to close 
                SetJawAngle(contactAngle - 2.5f);    // -2.5f to close jaw even more to make it look realistic grab

                // Add the reward for grabbing the object
                agent.GrabBlockReward();
            }
        }
    }

    public void RemoveBlockRB()
    {
        // Remove the rigid body component from it
        // Use currHoop from motor script ref.
        // Assert.IsNotNull(motor.currHoop);
        if (motor.currHoop == null)
        {
            return;
        }
        GameObject block = motor.currHoop;
        Rigidbody rb = block.GetComponent<Rigidbody>();
        if (rb != null)
        {
            // Debug.Log("[API] Removing RigidBody");
            Destroy(rb);
        }
        // TODO: Make sure to reassign this updated block with new parent to the dict mapping
        // code here...
    }

    public void SetJawAngle(float contactAngle)
    {
        UrdfJointMapping jointMap = jointNameToActiveJoint["jaw"];
        ArticulationDrive currentDrive = jointMap.Joint.xDrive;
        currentDrive.target = contactAngle;
        jointMap.Joint.xDrive = currentDrive;
        // Update the joint mapping and angle of contact in UrdfController
        controller.SetAngleOfContact(contactAngle);
        controller.SetJointMapping("jaw", jointMap);
    }

    public void SeparateBlockFromArm()
    {
        isColliding = false;
        otherJaw.isColliding = false;
        objectGrabbed = false;
        otherJaw.objectGrabbed = false;
        // Unparent the block when released
        GameObject parentTooltip = GameObject.Find("tool_midpoint");
        if (parentTooltip != null && parentTooltip.transform.childCount > 0)
        {
            Transform block = parentTooltip.transform.GetChild(0);
            // Set the block's parent to be the env prefab
            block.SetParent(topMostParent);
            // Add rigidbody component back to it
            block.gameObject.AddComponent<Rigidbody>();
            
            controller.isCollisionDetected = false;
        }
        // Debug.Log("Dropped");
    }

    private void ManualOnCollisionExit()
    {
        SeparateBlockFromArm();
    }

    private float CalculateAngleWithXAxis(Vector3 normal)
    {
        Vector3 xAxis = Vector3.right;

        // Calculate the angle using Vector3.Angle
        float angle = Vector3.Angle(normal, xAxis);

        // Since the jaw's only open upto +- 28.64 degrees, we'll clip it to that limit
        if ((angle < 0f) && (angle < -28.64f))
        {
            return -28.64f + 5f;    // 5f for adjustment of visuals to match
        }
        else if ((angle > 0f) && (angle > 28.64f))
        {
            return 28.64f - 5f;     // 5f for adjustment of visuals to match
        }

        return angle;
    }

    private void FixedUpdate()
    {
        if (controller.GetJawOpen() &&
            (objectGrabbed || otherJaw.objectGrabbed))
        {   
            ManualOnCollisionExit();
        }
    }


}
