
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Assertions;

public class JawCollision : MonoBehaviour
{
    private GameObject robot;
    [SerializeField]
    private UrdfJointController controller;
    public Dictionary<string, UrdfJointMapping> jointNameToActiveJoint;

    public bool isColliding;
    public JawCollision otherJaw;
    public bool objectGrabbed;
    public bool pickedBlockOnce = false;

    public int edgeLayer;

    public LowLevelMotor motor;

    private Transform topMostParent;

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
    }


    Transform GetTopMostParent(Transform child)
    {
        while (child.parent != null)
        {
            child = child.parent;
        }
        return child;
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
                    Destroy(rb);
                }
                GameObject tooltip = GameObject.Find("tool_midpoint");
                block.transform.SetParent(tooltip.transform);

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
                SetJawAngle(contactAngle - 2.5f);
            }
        }
    }

    public void RemoveBlockRB()
    {
        if (motor.currHoop == null)
        {
            return;
        }
        GameObject block = motor.currHoop;
        Rigidbody rb = block.GetComponent<Rigidbody>();
        if (rb != null)
        {
            Destroy(rb);
        }
    }

    public void SetJawAngle(float contactAngle)
    {
        UrdfJointMapping jointMap = jointNameToActiveJoint["jaw"];
        ArticulationDrive currentDrive = jointMap.Joint.xDrive;
        currentDrive.target = contactAngle;
        jointMap.Joint.xDrive = currentDrive;
        controller.SetAngleOfContact(contactAngle);
        controller.SetJointMapping("jaw", jointMap);
    }

    public void SeparateBlockFromArm()
    {
        isColliding = false;
        otherJaw.isColliding = false;
        objectGrabbed = false;
        otherJaw.objectGrabbed = false;
        GameObject parentTooltip = GameObject.Find("tool_midpoint");
        if (parentTooltip != null && parentTooltip.transform.childCount > 0)
        {
            Transform block = parentTooltip.transform.GetChild(0);
            block.SetParent(topMostParent);
            block.gameObject.AddComponent<Rigidbody>();
            
            controller.isCollisionDetected = false;
        }
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
            return -28.64f + 5f;
        }
        else if ((angle > 0f) && (angle > 28.64f))
        {
            return 28.64f - 5f;
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
