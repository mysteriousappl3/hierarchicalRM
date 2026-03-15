using UnityEngine;
using System.Collections.Generic;
using System.Collections;
using UnityEngine.Assertions;

public class LowLevelMotor: MonoBehaviour
{
    [SerializeField]
    private GameObject toolTip;
    [SerializeField]
    private Collider hoopEdgeOneCollider;
    [SerializeField]
    private Collider hoopEdgeTwoCollider;

    public GameObject currHoop;

    private Vector3 armPosition;
    private Vector3 armRotation;
    private float jawSignal;

    // Keep track of the mapping from peg numbers to their peg game objects
    [SerializeField]
    public List<GameObject> pegsInScene = new List<GameObject>();
    [SerializeField]
    public List<GameObject> hoopsInScene = new List<GameObject>();
    [SerializeField]
    public Dictionary<int, GameObject> pegNumberToObjectMapping = new Dictionary<int, GameObject>();
    // Keep track of the mapping from peg numbers to the hoop game objects that are inside the peg
    [SerializeField]
    public Dictionary<int, List<GameObject>> pegNumberToHoopObjMapping = new Dictionary<int, List<GameObject>>();

    // Peg Numbers start from 1.
    public int goalPegNumber;
    private int currPegNumber;
    private float hoopRadius;

    // Scripts references
    public RobotController robotCont;
    public JawCollision collisionCont;

    // Constants
    private const float speedMultiplier = 0.00115f;
    private const float epsilon = 1e-4f;
    private float pegHeight;

    public Vector3 GetArmPosition()
    {
        return armPosition;
    }

    void Start()
    {
        armPosition = Vector3.zero;
        armRotation = Vector3.zero;
        jawSignal = 0f;
        
        goalPegNumber = 0;
        currPegNumber = 0;
        // Since all peg's are of the same height, we can calculate using any peg
        pegHeight = pegsInScene[0].transform.position.y;

        // TODO: Remove once you do the cleanup in scene view management.
        // Add peg numbers and their game objects to the dictionary
        for (int i = 0; i < pegsInScene.Count; i++)
        {
            pegNumberToObjectMapping.Add(i + 1, pegsInScene[i]);
        }

        // TODO: Remove once you do the cleanup in scene view management.

        // We will initialize each scene as a tower of hanoi format meaning all the hoops are in the same pillar #1 and rest are empty lists
        // IMP NOTE: If the scene is diff, make sure to change the ordering of the hoops appropriately in below code
        for (int i = 0; i < pegsInScene.Count; i++)
        {
            int pegNum = i + 1;
            if (pegNum == 1)
            {
                pegNumberToHoopObjMapping.Add(pegNum, hoopsInScene);
            }
            else
            {
                // For rest of pillars (pegs), initialize with empty list indicating these have no hoops in them yet
                pegNumberToHoopObjMapping.Add(pegNum, new List<GameObject>());
            }
        }

        // Calculate radius of the hoop
        hoopRadius = Vector3.Distance(hoopEdgeOneCollider.bounds.center, hoopEdgeTwoCollider.bounds.center) / 2.0f;
    }

    public IEnumerator ToggleHoopTopSurfaceCollider(GameObject hoop, bool toggleValue)
    {
        yield return new WaitForSeconds(5); // Wait for 5 seconds before disabling/enabling

        if (hoop != null)
        {
            Transform topSupport = hoop.transform.Find("TopSupport");

            if (topSupport != null && topSupport.childCount >= 2)
            {
                topSupport.GetChild(0).GetComponent<MeshCollider>().enabled = toggleValue;
                topSupport.GetChild(1).GetComponent<MeshCollider>().enabled = toggleValue;
            }
        }
    }

    // Function to enable/disable collision between tooltip and hoop to avoid drag like behaviours or hoop from getting stuck
    public void IgnoreLayerCollision(bool toggleValue)
    {
        int layerHoopOuterColliders = LayerMask.NameToLayer("OuterBlockEdge");
        int layerHoopInnerColliders = LayerMask.NameToLayer("InnerBlockEdge");
        int layerToolTip = LayerMask.NameToLayer("IgnoreCamera");

        Physics.IgnoreLayerCollision(layerHoopInnerColliders, layerToolTip, toggleValue);
        Physics.IgnoreLayerCollision(layerHoopOuterColliders, layerToolTip, toggleValue);
    }


    /////////////////////////////////////

    // Move From Current Peg to Given Peg Location (Functions and Coroutine)

    /////////////////////////////////////

    public IEnumerator MoveCoroutine(int pegNumber)
    {
        goalPegNumber = pegNumber;
        yield return StartCoroutine(MoveTerminationCheck());
    }

    public IEnumerator MoveTerminationCheck()
    {
        // Align the hoop grabbed to center of current peg (Adjust X-Z coordinates)

        if (currPegNumber != 0 && currHoop != null)
        {
            bool currPegAdjustXZ = false;
            while (!currPegAdjustXZ)
            {
                currPegAdjustXZ = AlignHoopInPeg();
                yield return null;
            }
        }


        // Lift out of current peg

        float deltaY = pegHeight - toolTip.transform.position.y;
        while (deltaY > -0.15f)
        {
            AdjustArmHeight();
            deltaY = pegHeight - toolTip.transform.position.y;
            yield return null;
        }

        // Adjust the X-Z coordinates of the arm to reach the desired peg location
        bool adjustXZ = false;
        while (!adjustXZ)
        {
            adjustXZ = Move();
            yield return null;
        }
        currPegNumber = goalPegNumber;
    }

    
    public bool Move()
    {
        bool flagX = false;
        bool flagZ = false;

        GameObject goalPeg = pegNumberToObjectMapping[goalPegNumber];
        
        float deltaX = goalPeg.transform.position.x - toolTip.transform.position.x;
        float deltaZ = goalPeg.transform.position.z - toolTip.transform.position.z;

        if (collisionCont.objectGrabbed || collisionCont.otherJaw.objectGrabbed)
        {
            deltaX = goalPeg.transform.position.x - currHoop.transform.position.x;
            deltaZ = goalPeg.transform.position.z - currHoop.transform.position.z;

            // Move the robot arm's tool tip to the start peg position
            if (Mathf.Abs(deltaX) > 0.0075f)
            {
                float directionX = Mathf.Sign(deltaX);
                Vector3 pos = new Vector3(directionX * speedMultiplier, 0f, 0f);
                robotCont.MoveTip(pos, armRotation, jawSignal);
                armPosition = pos;
            }
            else
            {
                flagX = true;
            }

            // Move to desired Z-coordinate
            if (Mathf.Abs(deltaZ) > 0.0075f)
            {
                float directionZ = Mathf.Sign(deltaZ);
                Vector3 pos = new Vector3(0f, 0f, directionZ * speedMultiplier);
                robotCont.MoveTip(pos, armRotation, jawSignal);
                armPosition = pos;
            }
            else
            {
                flagZ = true;
            }

            return flagX && flagZ;
        }

        int size = pegNumberToHoopObjMapping[goalPegNumber].Count;
        if (size != 0)
        {
            List<GameObject> hoopsInPeg = pegNumberToHoopObjMapping[goalPegNumber];
            currHoop = hoopsInPeg[size - 1];  // Take the top-most hoop from this list.

            // Here we will call our function to disbale the top surface collider so we can grab it conveniently
            StartCoroutine(ToggleHoopTopSurfaceCollider(currHoop, false));

            // Extract the edge colliders from this hoop to determine which side is ideal to grab from

            // Note: The side of the hoop that's farthest away from the peg is the ideal grab edge
            // as this gives the arm sufficient room to open its jaw and grab the hoop.
            GameObject edgeOne = currHoop.transform.Find("OuterColliders/collider2").gameObject;
            GameObject edgeTwo = currHoop.transform.Find("OuterColliders/collider7").gameObject;

            Collider edgeOneCol = edgeOne.GetComponent<Collider>();
            Collider edgeTwoCol = edgeTwo.GetComponent<Collider>();

            // 1. Calculate edge distance from center of peg and edge colldier of hoop.
            float deltaEdgeOne = edgeOneCol.bounds.center.x - goalPeg.transform.position.x;
            float deltaEdgeTwo = edgeTwoCol.bounds.center.x - goalPeg.transform.position.x;

            // 2: Calculate target positions for both edges
            hoopRadius = Vector3.Distance(edgeOneCol.bounds.center, edgeTwoCol.bounds.center) / 2.0f;
            float targetEdgeOneX = goalPeg.transform.position.x + hoopRadius * Mathf.Sign(deltaEdgeOne);
            float targetEdgeTwoX = goalPeg.transform.position.x + hoopRadius * Mathf.Sign(deltaEdgeTwo);

            // 3: Select the edge with the larger absolute delta
            float targetX = Mathf.Abs(deltaEdgeOne) > Mathf.Abs(deltaEdgeTwo) ? targetEdgeOneX : targetEdgeTwoX;
            string targetEdge = Mathf.Abs(deltaEdgeOne) > Mathf.Abs(deltaEdgeTwo) ? "Edge One" : "Edge Two";

            // 4: Calculate the difference between toolTip and the target position
            float adjustedToolTipX = toolTip.transform.position.x;
            float diff = targetX - adjustedToolTipX;

            // 5: Move the toolTip toward the target position
            if (Mathf.Abs(diff) > 0.005f) // Threshold to stop movement
            {
                float directionX = Mathf.Sign(diff); // Determine movement direction
                Vector3 pos = new Vector3(directionX * speedMultiplier, 0f, 0f);

                robotCont.MoveTip(pos, armRotation, -1f);

            }
            else
            {
                // Stop movement if close enough
                flagX = true;
            }
        }
        else
        {
            // Move the robot arm's tool tip to the goal peg position
            if (Mathf.Abs(deltaX) > 0.23f)
            {
                float directionX = Mathf.Sign(deltaX);
                Vector3 pos = new Vector3(directionX * speedMultiplier, 0f, 0f);
                robotCont.MoveTip(pos, armRotation, -1f);
                armPosition = pos;
            }
            else
            {
                flagX = true;
            }
        }

        // Move to desired Z-coordinate
        if (Mathf.Abs(deltaZ) > 0.01f)
        {
            float directionZ = Mathf.Sign(deltaZ);
            Vector3 pos = new Vector3(0f, 0f, directionZ * speedMultiplier);
            robotCont.MoveTip(pos, armRotation, 0f);
            armPosition = pos;
        }
        else
        {
            flagZ = true;
        }

        return flagX && flagZ;
    }

    // This function will adjust the X-Z coordinates of the hoop in the peg it's currently in
    // so that the hoop is in the center of the peg.
    // This function is used in MoveCoroutine() in the case when a hoop is grabbed and we're moving to
    // another goal peg location.
    // In the case that multiple hoops are stacked, they may be shifted and we cannot simply first
    // adjust the Y-Coordinate to lift it out as hoop may be inclined at an angle and drag against peg and cause issues
    public bool AlignHoopInPeg(int pegNum = 0)
    {
        bool flagX = false;
        bool flagZ = false;


        GameObject currPeg;

        if (pegNum != 0)
        {
            currPeg = pegNumberToObjectMapping[pegNum];
        }
        else
        {
            currPeg = pegNumberToObjectMapping[currPegNumber];
        }

        float deltaX = currPeg.transform.position.x - currHoop.transform.position.x;
        float deltaZ = currPeg.transform.position.z - currHoop.transform.position.z;

        // Move the robot arm's tool tip to align to center peg location
        float threshold = 0.015f;
        if (deltaX > threshold)
        {
            float directionX = +1f;
            Vector3 pos = new Vector3(directionX * speedMultiplier, 0f, 0f);
            robotCont.MoveTip(pos, armRotation, jawSignal);
            armPosition = pos;
        }
        else if (deltaX < -threshold)
        {
            float directionX = -1f; 
            Vector3 pos = new Vector3(directionX * speedMultiplier, 0f, 0f);
            robotCont.MoveTip(pos, armRotation, jawSignal);
            armPosition = pos;
        }
        else
        {
            flagX = true;
        }

        if (deltaZ > threshold)
        {
            float directionZ = 1f; 
            Vector3 pos = new Vector3(0f, 0f, directionZ * speedMultiplier);
            robotCont.MoveTip(pos, armRotation, jawSignal);
            armPosition = pos;
        }
        else if (deltaZ < -threshold)
        {
            float directionZ = -1f; 
            Vector3 pos = new Vector3(0f, 0f, directionZ * speedMultiplier);
            robotCont.MoveTip(pos, armRotation, jawSignal);
            armPosition = pos;
        }
        else
        {
            flagZ = true;
        }

        return flagX && flagZ;
    }


    // This function adjusts the tool tip/arm's height to be above the peg
    // It serves as a helper function for the MoveCoroutine()
    public void AdjustArmHeight()
    {
        float deltaY = Mathf.Abs(pegHeight - toolTip.transform.position.y);

        if (deltaY < 1f)
        {
            float directionY = Mathf.Sign(deltaY);
            Vector3 pos = new Vector3(0f, directionY * speedMultiplier, 0f);
            robotCont.MoveTip(pos, armRotation, jawSignal);
            armPosition = pos;
        }

    }

    ////////////////////////////////////

    // Grab Hoop (Functions and Coroutine)

    ///////////////////////////////////// 

    public IEnumerator GrabCoroutine()
    {
        // Re-enable physics layer collision between hoop colliders and tooltip
        IgnoreLayerCollision(false);

        // Enable the arm's to grab the block. We will first set the y-axis
        // Following this, we will enable it's ability to drab and force arm close which will trigger a realistic looking grab
        collisionCont.GRAB_BLOCK_ENABLED = true;

        // At this stage, we would have moved to the desired peg to grab the hoop.
        // If hoop doesn't exist in the currPegNumber that we're at presently,
        // this means that this hoop has no peg in it (or arm isn't grabbing the hoop).
        // Simply return

        if (currPegNumber == 0 || currHoop == null) {
            yield break;
        }

        int size = pegNumberToHoopObjMapping[currPegNumber].Count;
        if (size == 0)
        {
            yield break;
        }
        
        collisionCont.RemoveBlockRB();
        yield return StartCoroutine(GrabTerminationCheck());
    }

    public IEnumerator GrabTerminationCheck()
    {
        float proximity = currHoop.transform.position.y - toolTip.transform.position.y;

        while (proximity <= 0.1f)
        {
            Grab(1.25f);
            proximity = currHoop.transform.position.y - toolTip.transform.position.y;
            if (collisionCont.objectGrabbed || collisionCont.otherJaw.objectGrabbed)
            {   
                break;
            }
            yield return null;
        }
    }

    public void Grab(float signal)
    {
        jawSignal = signal;
        // Move to desired Y-coordinate
        float deltaY = currHoop.transform.position.y - toolTip.transform.position.y;
        if (deltaY <= 0.1f)
        {
            float directionY = -1f;

            Vector3 pos = new Vector3(0f, directionY * speedMultiplier, 0f);
            robotCont.MoveTip(pos, armRotation, jawSignal);
            armPosition = pos;
        }
    }

    ////////////////////////////////////

    // Drop Hoop Function

    /////////////////////////////////////

    public IEnumerator DropCoroutine()
    {
        // Disable layer collision between the tooltip and the hoops edge colliders
        IgnoreLayerCollision(true);
        
        collisionCont.GRAB_BLOCK_ENABLED = false;

        // At this stage, we would have moved to the desired peg to drop the hoop.
        // If currHoop variable is null,
        // this means that this hoop has no peg in it (or arm isn't grabbing the hoop).
        // Simply return

        if (currHoop == null)
        {
            yield break;
        }

        yield return StartCoroutine(DropTerminationCheck());
    }

    public IEnumerator DropTerminationCheck()
    {
        // Assert that the hoop is held. If hoop not held, simply return and do nothing
        if (!collisionCont.objectGrabbed && !collisionCont.otherJaw.objectGrabbed)
        {
            yield break;
        }

        // Edge Case Check: Hoops stacked and they're tilted so first align them to center of current peg and then begin lifting
        // Basically, we want to after grab, align the arm with the hoop so that hoop is in the center of the peg
        // so that the hoop is in center and ready to be easily lifted when MoveCoroutine() is called next.

        // 1. Align the hoop grabbed to center of current peg (Adjust X-Z coordinates)

        if (currPegNumber != 0 && currHoop != null)
        {
            bool currPegAdjustXZ = false;
            while (!currPegAdjustXZ)
            {
                currPegAdjustXZ = AlignHoopInPeg();
                // Ensure the coroutine yields control
                yield return null;
            }
        }

        float deltaY = pegHeight - toolTip.transform.position.y;
        bool flag = false;

        while (!flag)
        {
            flag = Drop(1.25f);
            deltaY = pegHeight - toolTip.transform.position.y;
            yield return null;
        }

        collisionCont.SeparateBlockFromArm();

        GameObject hoopToDrop = currHoop;
        StartCoroutine(ToggleHoopTopSurfaceCollider(hoopToDrop, true));

        // Remove the previous entry of this hoop from another peg where it was picked up from
        RemoveHoopFromMapping();

        pegNumberToHoopObjMapping[currPegNumber].Add(currHoop);
        
        currHoop = null;
    }

    public bool Drop(float signal)
    {
        Vector3 hoopBottomDir = -currHoop.transform.up;
        Vector3 XZPlaneNormal = Vector3.up;

        float tiltAngle = 180 - Vector3.Angle(hoopBottomDir, XZPlaneNormal);

        bool flag = false;
        jawSignal = signal;

        // If there is is no hoop in this peg that we are aiming to drop in, we want the arm
        // to go all the way down before dropping the hoop.

        // If there are existing hoop(s) in this peg, we want to take the top most peg's Y-coordinate and drop the hoop
        // just above that.

        int size = pegNumberToHoopObjMapping[currPegNumber].Count;
        if (size == 0)
        {
            // No pegs in this hoop

            float deltaY = pegHeight - toolTip.transform.position.y;

            float dropHeight = 0.075f;

            if (tiltAngle >= 5.0) {
                dropHeight += 0.175f;
            }

            float tipY = toolTip.transform.position.y;
            if (tipY > dropHeight)
            {
                float directionY = -1f;
                Vector3 pos = new Vector3(0f, directionY * speedMultiplier, 0f);
                robotCont.MoveTip(pos, armRotation, signal);
                armPosition = pos;
            }
            else
            {
                flag = true;
            }
        }
        else
        {

            GameObject topHoop = pegNumberToHoopObjMapping[currPegNumber][size - 1];
            float yLimit = topHoop.transform.position.y;
            float deltaY = toolTip.transform.position.y - yLimit;

            float dropHeight = 0.175f;

            if (tiltAngle >= 5.0) {
                dropHeight += 0.275f; 
            }

            if (deltaY > dropHeight)
            {
                float directionY = -1f;
                Vector3 pos = new Vector3(0f, directionY * speedMultiplier, 0f);
                robotCont.MoveTip(pos, armRotation, signal);
                armPosition = pos;
            }
            else
            {
                flag = true;
            }
        }

        return flag;
    }

    private bool RemoveHoopFromMapping()
    {
        foreach (var entry in pegNumberToHoopObjMapping)
        {
            int pegNumber = entry.Key;
            List<GameObject> hoopList = entry.Value;

            for (int i = 0; i < hoopList.Count; i++)
            {
                if (hoopList[i] != null && hoopList[i].name == currHoop.name)
                {
                    hoopList.RemoveAt(i);
                    return true;
                }
            }
        }
        return false;
    }

}
