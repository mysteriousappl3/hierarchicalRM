using UnityEngine;
using System.Collections.Generic;
using System.Collections;
using UnityEngine.Assertions;

public class LowLevelMotor: MonoBehaviour
{
    // Game object references
    [SerializeField]
    private GameObject toolTip;
    [SerializeField]
    // TODO: Add dictionary mapping from hoop to its edge colliders so you can dynamically calculate radius of multiple
    // varying sizes of hoops later.
    // These edge colliders are used to dynamically calculate the radius of the hoop
    // We also use these to calculate which side of the hoop is farthest away from the peg so it's easier
    // for the arm to grab from that side.
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
    // Eg: Peg with label A : 1, B: 2, C: 3, etc...
    public int goalPegNumber;
    private int currPegNumber;
    private float hoopRadius;

    // Scripts references
    public RobotController robotCont;
    public UrdfJointController urdfCont;
    public JawCollision collisionCont;

    // Constants
    private const float speedMultiplier = 0.00115f; // original
    //private const float speedMultiplier = 0.00075f;
    private const float epsilon = 1e-4f;
    // Since all peg's are of same height, we will store this constant
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

        // Add peg numbers and their game objects to the dictionary
        for (int i = 0; i < pegsInScene.Count; i++)
        {
            pegNumberToObjectMapping.Add(i + 1, pegsInScene[i]);    // index starts from 0 so i + 1
        }
        //pegNumberToObjectMapping.Add(1, pegOne);
        //pegNumberToObjectMapping.Add(2, pegTwo);
        //pegNumberToObjectMapping.Add(3, pegThree);

        // Add peg numbers and the hoops to the dictionary. This order represents bottom up.

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

        //pegNumberToHoopObjMapping[1] = new List<GameObject> { hoopOne };
        //pegNumberToHoopObjMapping[2] = new List<GameObject> { hoopTwo };
        //pegNumberToHoopObjMapping[3] = new List<GameObject>();

        // Calculate radius of the hoop
        hoopRadius = Vector3.Distance(hoopEdgeOneCollider.bounds.center, hoopEdgeTwoCollider.bounds.center) / 2.0f;
        // Add small constant to calculate relative to the outer most edge faces
        //hoopRadius += 0.012f;
        // Debug.Log("Hoop Radius = " + hoopRadius);
    }

    public IEnumerator ToggleHoopTopSurfaceCollider(GameObject hoop, bool toggleValue)
    {
        yield return new WaitForSeconds(5); // Wait for 5 seconds before disabling/enabling

        if (hoop != null)
        {
            Transform topSupport = hoop.transform.Find("TopSupport");

            if (topSupport != null && topSupport.childCount >= 2)
            {
                // UnityEngine.Debug.Log("Toggling the mesh collider");
                // We can assume that we have already called the move function so we have already assigned the curr hoop that
                // we are going to pick up via grab call next.
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
        // COMMENTED BECAUSE: EDge case where it lowers and it needs to go to other side to grab and peg in its path.
        //if (currPegNumber == goalPegNumber)
        //{
        //    // Only adjust the X-Z location

        //    // Adjust the X-Z coordinates of the arm to reach the desired peg location
        //    bool adjustXZ = false;
        //    while (!adjustXZ)
        //    {
        //        adjustXZ = Move();
        //        // Ensure the coroutine yields control
        //        yield return null;
        //    }

        //    currPegNumber = goalPegNumber;
        //    Debug.Log("[Move] : Reached the desired peg location!");
        //}
        //else
        //{
        //    float deltaY = pegHeight - toolTip.transform.position.y;
        //    while (deltaY > -0.15f)
        //    {
        //        AdjustArmHeight();
        //        deltaY = pegHeight - toolTip.transform.position.y;
        //        // Ensure the coroutine yields control
        //        yield return null;
        //    }

        //    // We have now successfully adjusted the tool tip's height to be above the peg
        //    Debug.Log("[Move] : Reached desired height!");

        //    // 2. Adjust the X-Z coordinates of the arm to reach the desired peg location
        //    bool adjustXZ = false;
        //    while (!adjustXZ)
        //    {
        //        adjustXZ = Move();
        //        // Ensure the coroutine yields control
        //        yield return null;
        //    }

        //    currPegNumber = goalPegNumber;
        //    Debug.Log("[Move] : Reached the desired peg location!"); 
        //}


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

        // 2. Adjust the Y-Coordinate to lift the arm above the peg

        // TODO (Completed): If the arm is under the peg and near the MoveTo peg location,
        // don't make it lift it's vertical and simply only adjust X-Z
        // Eg: Move(A) -> Grab -> Move (C) -> Drop (will lower inside peg C) -> Move (C)
        // ---> now should only adjust x-z instead of adjusting it's y too.


        // 3. Lift out of current peg

        float deltaY = pegHeight - toolTip.transform.position.y;
        // Debug.Log("move coroutine : deltaY = " + deltaY);
        while (deltaY > -0.15f)
        {
            AdjustArmHeight();
            deltaY = pegHeight - toolTip.transform.position.y;
            // Ensure the coroutine yields control
            yield return null;
        }

        // We have now successfully adjusted the tool tip's height to be above the peg
        // Debug.Log("[Move] : Reached desired height!");

        // 2. Adjust the X-Z coordinates of the arm to reach the desired peg location
        bool adjustXZ = false;
        while (!adjustXZ)
        {
            adjustXZ = Move();
            // Ensure the coroutine yields control
            yield return null;
        }

        currPegNumber = goalPegNumber;
        // Debug.Log("[Move] : Reached the desired peg location!");
    }

    
    public bool Move()
    {
        bool flagX = false;
        bool flagZ = false;

        // Add error checking if goalPegNumber exists in our map
        GameObject goalPeg = pegNumberToObjectMapping[goalPegNumber];
        // Since the 'pegNumberToHoopObjMapping' represents the hoop-peg state representation at any given instant,
        // we know that goalPegNumber is the peg where hoop exists.
        
        float deltaX = goalPeg.transform.position.x - toolTip.transform.position.x;
        float deltaZ = goalPeg.transform.position.z - toolTip.transform.position.z;

        if (collisionCont.objectGrabbed || collisionCont.otherJaw.objectGrabbed)
        {
            // Assert that hoop is being grabbed i.e currHoop is not null.
            // Assert.IsNotNull(currHoop);

            deltaX = goalPeg.transform.position.x - currHoop.transform.position.x;
            deltaZ = goalPeg.transform.position.z - currHoop.transform.position.z;

            // Move the robot arm's tool tip to the start peg position
            // 1. Move to the desired X-coordinate

            // Debug.Log("Goal DeltaX = " + deltaX);
            // If the dist between the x-coord of hoop and goal peg is > a threhsold of 0.01, then keep moving to reduce it.
            // Otherwise, we've reached desired flagX so set True. Similarly for other case
            if (Mathf.Abs(deltaX) > 0.0075f)
            {
                // Debug.Log("INSIDE DeltaX = " + deltaX);
                // 1.1 Calculate the direction to move the arm in
                float directionX = Mathf.Sign(deltaX);
                // 1.2 Pass the new change in direction to the position vector
                Vector3 pos = new Vector3(directionX * speedMultiplier, 0f, 0f);
                //Vector3 newPos = new Vector3(3f, 0f, 0f) + armPosition;
                // Move(pos, jawSignal);
                //robotCont.MoveTip(pos * Time.deltaTime, armRotation, jawSignal);
                robotCont.MoveTip(pos, armRotation, jawSignal);
                armPosition = pos;
            }
            else
            {
                flagX = true;
            }

            // 2. Move to desired Z-coordinate
            // Debug.Log("Goal DeltaZ = " + deltaZ);
            if (Mathf.Abs(deltaZ) > 0.0075f)
            {
                // Debug.Log("INSIDE DeltaZ = " + deltaZ);
                // 2.1 Calculate the direction to move the arm in
                float directionZ = Mathf.Sign(deltaZ);
                // 1.2 Pass the new change in direction to the position vector
                Vector3 pos = new Vector3(0f, 0f, directionZ * speedMultiplier);
                //Vector3 newPos = new Vector3(3f, 0f, 0f) + armPosition;
                // Move(pos, jawSignal);
                //robotCont.MoveTip(pos * Time.deltaTime, armRotation, jawSignal);
                robotCont.MoveTip(pos, armRotation, jawSignal);
                armPosition = pos;
            }
            else
            {
                flagZ = true;
            }

            return flagX && flagZ;
        }


        // Of the two edges, whichever has the greatest Abs() value, that's the side the arm should move to
        // We will then try to match the deltaX to be close to the deltaEdgeOne or two.
        // This will be Abs diff check <= 0.01f.
        // Reason being that deltaEdge and deltaX calculated relative to goalPeg so in either case,
        // when we do Abs of these two, we're tryna reach the edge side and the arm.
        // This is for the case when hoop isn't grabbed

        // TODO: Check if peg has a hoop inside it. If yes, use hoop transform instead of peg when not grabbed
        // Otherwise, use the goalPeg transform.

        // TODO: Basically, check which side of the hoop is ideal to grab from.


        // Retrieve for the goalPegNumber hoop that we're at, take the top most hoop (last value in array)
        // from this peg
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
            // (We decided to use two opposide edge colliders: OuterEdge->Collider2 and OuterEdge->Collider7)
            GameObject edgeOne = currHoop.transform.Find("OuterColliders/collider2").gameObject;
            GameObject edgeTwo = currHoop.transform.Find("OuterColliders/collider7").gameObject;

            // Assert found edge collider game objects aren't null
            //Assert.IsNotNull(edgeOne);
            //Assert.IsNotNull(edgeTwo);

            Collider edgeOneCol = edgeOne.GetComponent<Collider>();
            Collider edgeTwoCol = edgeTwo.GetComponent<Collider>();

            // 1. Calculate edge distance from center of peg and edge colldier of hoop.
            float deltaEdgeOne = edgeOneCol.bounds.center.x - goalPeg.transform.position.x;
            float deltaEdgeTwo = edgeTwoCol.bounds.center.x - goalPeg.transform.position.x;

            // 2: Calculate target positions for both edges
            hoopRadius = Vector3.Distance(edgeOneCol.bounds.center, edgeTwoCol.bounds.center) / 2.0f;
            float targetEdgeOneX = goalPeg.transform.position.x + hoopRadius * Mathf.Sign(deltaEdgeOne);
            float targetEdgeTwoX = goalPeg.transform.position.x + hoopRadius * Mathf.Sign(deltaEdgeTwo);

            // Debug.Log("EDGE ONE PROXIMITY TO PEG = " + deltaEdgeOne);
            // Debug.Log("EDGE TWO PROXIMITY TO PEG = " + deltaEdgeTwo);

            // 3: Select the edge with the larger absolute delta
            float targetX = Mathf.Abs(deltaEdgeOne) > Mathf.Abs(deltaEdgeTwo) ? targetEdgeOneX : targetEdgeTwoX;
            string targetEdge = Mathf.Abs(deltaEdgeOne) > Mathf.Abs(deltaEdgeTwo) ? "Edge One" : "Edge Two";

            // Debug.Log("Aiming to reach final X Loc = " + targetX);
            // Debug.Log("Tool Tip's X Loc = " + toolTip.transform.position.x);
            // 4: Calculate the difference between toolTip and the target position
            float adjustedToolTipX = toolTip.transform.position.x;
            float diff = targetX - adjustedToolTipX;

            // Debug.Log("DiffX = " + diff);
            // 5: Move the toolTip toward the target position
            if (Mathf.Abs(diff) > 0.005f) // Threshold to stop movement
            {
                float directionX = Mathf.Sign(diff); // Determine movement direction
                Vector3 pos = new Vector3(directionX * speedMultiplier, 0f, 0f);

                // Move the toolTip
                // robotCont.MoveTip(pos * Time.deltaTime, armRotation, -1f);
                robotCont.MoveTip(pos, armRotation, -1f);

                // Debugging movement
                // Debug.Log($"Moving toolTip towards {targetEdge}, directionX = {directionX}");
            }
            else
            {
                // Stop movement if close enough
                // Debug.Log($"toolTip has reached {targetEdge} at the desired radius!");
                flagX = true;
            }
        }
        else
        {
            // Debug.Log("This peg has no hoop in it so simply move close to this peg.");

            // Move the robot arm's tool tip to the goal peg position
            //// 1. Move to the desired X-coordinate

            // Debug.Log("Outside If Goal DeltaX = " + deltaX);
            if (Mathf.Abs(deltaX) > 0.23f)  // TODO: Needs to change
            {
                // 1.1 Calculate the direction to move the arm in
                float directionX = Mathf.Sign(deltaX);
                // 1.2 Pass the new change in direction to the position vector
                Vector3 pos = new Vector3(directionX * speedMultiplier, 0f, 0f);
                //Vector3 newPos = new Vector3(3f, 0f, 0f) + armPosition;
                // Move(pos, jawSignal);
                //robotCont.MoveTip(pos * Time.deltaTime, armRotation, -1f);
                robotCont.MoveTip(pos, armRotation, -1f);
                armPosition = pos;
            }
            else
            {
                flagX = true;
            }
        }

        // 2. Move to desired Z-coordinate
        // Debug.Log("Goal DeltaZ = " + deltaZ);
        if (Mathf.Abs(deltaZ) > 0.01f)
        {
            // 2.1 Calculate the direction to move the arm in
            float directionZ = Mathf.Sign(deltaZ);
            // 1.2 Pass the new change in direction to the position vector
            Vector3 pos = new Vector3(0f, 0f, directionZ * speedMultiplier);
            //Vector3 newPos = new Vector3(3f, 0f, 0f) + armPosition;
            // Move(pos, jawSignal);
            //robotCont.MoveTip(pos * Time.deltaTime, armRotation, 0f);
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
        // 1. Move to the desired X-coordinate

        // Debug.Log("Curr DeltaX = " + deltaX);
        float threshold = 0.015f;
        if (deltaX > threshold)
        {
            // 1.1 Calculate the direction to move the arm in
            //float directionX = Mathf.Sign(deltaX);
            float directionX = +1f; // Move in positive direction to be less than threshold since we need to move arm in the dir
            // 1.2 Pass the new change in direction to the position vector
            Vector3 pos = new Vector3(directionX * speedMultiplier, 0f, 0f);
            //Vector3 newPos = new Vector3(3f, 0f, 0f) + armPosition;
            // Move(pos, jawSignal);
            //robotCont.MoveTip(pos * Time.deltaTime, armRotation, jawSignal);
            robotCont.MoveTip(pos, armRotation, jawSignal);
            armPosition = pos;
        }
        else if (deltaX < -threshold)
        {
            // 1.1 Calculate the direction to move the arm in
            //float directionX = Mathf.Sign(deltaX);
            float directionX = -1f; 
            // 1.2 Pass the new change in direction to the position vector
            Vector3 pos = new Vector3(directionX * speedMultiplier, 0f, 0f);
            //Vector3 newPos = new Vector3(3f, 0f, 0f) + armPosition;
            // Move(pos, jawSignal);
            //robotCont.MoveTip(pos * Time.deltaTime, armRotation, jawSignal);
            robotCont.MoveTip(pos, armRotation, jawSignal);
            armPosition = pos;
        }
        else
        {
            flagX = true;
        }

        // 2. Move to desired Z-coordinate which is center of current peg location
        // Debug.Log("Curr DeltaZ = " + deltaZ);
        if (deltaZ > threshold)
        {
            // 2.1 Calculate the direction to move the arm in
            //float directionZ = Mathf.Sign(deltaZ);
            float directionZ = 1f; 
            // 1.2 Pass the new change in direction to the position vector
            Vector3 pos = new Vector3(0f, 0f, directionZ * speedMultiplier);
            //Vector3 newPos = new Vector3(3f, 0f, 0f) + armPosition;
            // Move(pos, jawSignal);
            //robotCont.MoveTip(pos * Time.deltaTime, armRotation, jawSignal);
            robotCont.MoveTip(pos, armRotation, jawSignal);
            armPosition = pos;
        }
        else if (deltaZ < -threshold)
        {
            // 2.1 Calculate the direction to move the arm in
            //float directionZ = Mathf.Sign(deltaZ);
            float directionZ = -1f; 
            // 1.2 Pass the new change in direction to the position vector
            Vector3 pos = new Vector3(0f, 0f, directionZ * speedMultiplier);
            //Vector3 newPos = new Vector3(3f, 0f, 0f) + armPosition;
            // Move(pos, jawSignal);
            // robotCont.MoveTip(pos * Time.deltaTime, armRotation, jawSignal);
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

        // When the deltaY becomes -, it indicates the toolTip is above the peg.
        // For the current environment setup, we find 0.15 units above the peg to be ideal
        // to raise the arm even when it's carrying the hoop without getting stick against the tip of any peg
        // Debug.Log("DeltaY = " + deltaY);
        if (deltaY < 1f)
        {
            // Calculate the direction to move the arm in
            float directionY = Mathf.Sign(deltaY);
            // Pass the new change in direction to the position vector
            Vector3 pos = new Vector3(0f, directionY * speedMultiplier, 0f);
            
            // robotCont.MoveTip(pos * Time.deltaTime, armRotation, jawSignal);
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
        // Debug.Log("Re-enable layer collision");
        IgnoreLayerCollision(false);

        // Enable the arm's to grab the block. We will first set the y-axis
        // Following this, we will enable it's ability to drab and force arm close which will trigger a realistic looking grab
        collisionCont.GRAB_BLOCK_ENABLED = true;

        // At this stage, we would have moved to the desired peg to grab the hoop.
        // If hoop doesn't exist in the currPegNumber that we're at presently,
        // this means that this hoop has no peg in it (or arm isn't grabbing the hoop).
        // Simply return

        if (currPegNumber == 0 || currHoop == null) {
            // Debug.Log("[Grab] Please move to a peg first!");
            yield break;
        }

        int size = pegNumberToHoopObjMapping[currPegNumber].Count;
        // Debug.Log("[Grab] Size = " + size);
        if (size == 0)
        {
            // Debug.Log("[Grab] This peg has no hoop to grab!");
            yield break;
        }
        
        // Remove rigidbody from the hoop
        collisionCont.RemoveBlockRB();
        // Start the coroutine to lower arm and grab the block
        yield return StartCoroutine(GrabTerminationCheck());
    }

    public IEnumerator GrabTerminationCheck()
    {
        // DON'T CALL IN GRAB. IT MOVES AWAY FROM THE HOOP! Because Abs() > 0.01f in x-dir.

        //// Edge Case Check: Hoops stacked and they're tilted so first align them to center of current peg and then begin lifting
        //// Basically, we want to after grab, align the arm with the hoop so that hoop is in the center of the peg
        //// so that the hoop is in center and ready to be easily lifted when MoveCoroutine() is called next.

        //// 1. Align the hoop grabbed to center of current peg (Adjust X-Z coordinates)

        //if (currPegNumber != 0 && currHoop != null)
        //{
        //    bool currPegAdjustXZ = false;
        //    while (!currPegAdjustXZ)
        //    {
        //        currPegAdjustXZ = AlignHoopInPeg();
        //        // Ensure the coroutine yields control
        //        yield return null;
        //    }
        //}
        //Debug.Log("[Grab] CURR HOOP = " + currHoop);
        float proximity = currHoop.transform.position.y - toolTip.transform.position.y;
        // Debug.Log("ABS DIFF BETWEEN X-AXIS OF HOOP AND TIP = " + Mathf.Abs(currHoop.transform.position.x - toolTip.transform.position.x));
        // Debug.Log("ABS DIFF BETWEEN z-AXIS OF HOOP AND TIP = " + Mathf.Abs(currHoop.transform.position.z - toolTip.transform.position.z));
        // Debug.Log("[Before Grab] Proximity = " + proximity);
        while (proximity <= 0.1f)
        {
            // Passing signal of 1.25f to open the jaw to maximum limit to grab the hoop.
            Grab(1.25f);
            proximity = currHoop.transform.position.y - toolTip.transform.position.y;
            // Debug.Log("[Grab] Proximity of hoop grab = " + proximity);
            // If we grabbed the hoop, break immediately
            if (collisionCont.objectGrabbed || collisionCont.otherJaw.objectGrabbed)
            {   
                break;
            }
            // Yield execution until the next frame
            yield return null;
        }
        // Debug.Log("[Grab End] Proximity out of loop of hoop grab = " + proximity);
        // Debug.Log("Grabbed the hoop!");
    }

    public void Grab(float signal)
    {
        jawSignal = signal;

        // Move to desired Y-coordinate
        
        // Use currHoop since before the coroutine starts, we check if currHoop exists or not
        float deltaY = currHoop.transform.position.y - toolTip.transform.position.y;
        // Debug.Log("Abs Hoop DeltaY = " + Mathf.Abs(deltaY));
        if (deltaY <= 0.1f) // Continue to go down until we detect a object/hoop grab from collisionCont.
        {
            // 2.1 Calculate the direction to move the arm in
            //float directionY = Mathf.Sign(deltaY);

            float directionY = -1f; // Since grab always goes down, we will fix direction to be -ve.

            // 1.2 Pass the new change in direction to the position vector
            Vector3 pos = new Vector3(0f, directionY * speedMultiplier, 0f);
            //robotCont.MoveTip(pos * Time.deltaTime, armRotation, jawSignal);
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
        // Debug.Log("Disable layer collision");
        IgnoreLayerCollision(true);
        
        collisionCont.GRAB_BLOCK_ENABLED = false;

        // At this stage, we would have moved to the desired peg to drop the hoop.
        // If currHoop variable is null,
        // this means that this hoop has no peg in it (or arm isn't grabbing the hoop).
        // Simply return

        if (currHoop == null)
        {
            // Debug.Log("[Drop] Arm isn't grabbing any hoop!");
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

        // Assert that the currHoop is not null as this means that the arm is grabbing a hoop
        // Assert.IsNotNull(currHoop);

        float deltaY = pegHeight - toolTip.transform.position.y;
        bool flag = false;
        //while (deltaY < 0.6f)
        //{
        //    // Signal of 2.25 to make jaw open
        //    Drop(1.25f);
        //    // deltaY = pegHeight - currHoop.transform.position.y;
        //    deltaY = pegHeight - toolTip.transform.position.y;
        //    Debug.Log("[Drop] DeltaY Coroutine = " + deltaY);
        //    // Yield execution until the next frame
        //    yield return null;
        //}

        while (!flag)
        {
            // Signal of 2.25 to make jaw open
            flag = Drop(1.25f);
            // deltaY = pegHeight - currHoop.transform.position.y;
            deltaY = pegHeight - toolTip.transform.position.y;
            // Debug.Log("[Drop] DeltaY Coroutine = " + deltaY);
            // Yield execution until the next frame
            yield return null;
        }

        collisionCont.SeparateBlockFromArm();

        // Before we reset the object currHoop to null lets after 5 seconds re-enable the top surface collider
        GameObject hoopToDrop = currHoop;
        StartCoroutine(ToggleHoopTopSurfaceCollider(hoopToDrop, true));

        // Remove the previous entry of this hoop from another peg where it was picked up from
        RemoveHoopFromMapping();

        // Before setting currHoop to be null, update the pegToHoop mapping dict
        // Debug.Log("Adding currHoop obj to peg# = " + currPegNumber);
        pegNumberToHoopObjMapping[currPegNumber].Add(currHoop);
        
        // Set currHoop to be null
        currHoop = null;
        // Debug.Log("Drooped the hoop!"); 
    }

    public bool Drop(float signal)
    {

        // Calculate the tilt of the hoop
        Vector3 hoopBottomDir = -currHoop.transform.up;
        Vector3 XZPlaneNormal = Vector3.up;

        float tiltAngle = 180 - Vector3.Angle(hoopBottomDir, XZPlaneNormal);
        // Debug.Log("TILT ANGLE = " + tiltAngle);

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

            float dropHeight = 0.075f; // This is how low you want to go

            if (tiltAngle >= 5.0) {
                dropHeight += 0.175f;   // Make it drop early to avoid arm getting stuck when trying to lower for drop
            }

            float tipY = toolTip.transform.position.y;
            // if (deltaY < pegHeight - 0.25f)
            if (tipY > dropHeight)
            {
                // 2.1 Calculate the direction to move the arm in
                float directionY = -1f; // Since we always want to lower for drop
                // 1.2 Pass the new change in direction to the position vector
                Vector3 pos = new Vector3(0f, directionY * speedMultiplier, 0f);

                // collisionCont.SeparateBlockFromArm();
                // robotCont.MoveTip(pos * Time.deltaTime, armRotation, signal);
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
            // Get the height of the top most hoop

            GameObject topHoop = pegNumberToHoopObjMapping[currPegNumber][size - 1];
            float yLimit = topHoop.transform.position.y;
            float deltaY = toolTip.transform.position.y - yLimit;

            float dropHeight = 0.175f;

            if (tiltAngle >= 5.0) {
                dropHeight += 0.275f;   // Make it drop early to avoid arm getting stuck when trying to lower for drop
            }

            if (deltaY > dropHeight)
            {
                // 2.1 Calculate the direction to move the arm in
                float directionY = -1f; // Since we always want to lower for drop
                // 1.2 Pass the new change in direction to the position vector
                Vector3 pos = new Vector3(0f, directionY * speedMultiplier, 0f);

                // collisionCont.SeparateBlockFromArm();
                // robotCont.MoveTip(pos * Time.deltaTime, armRotation, signal);
                robotCont.MoveTip(pos, armRotation, signal);
                armPosition = pos;
            }
            else
            {
                flag = true;
            }
        }

        return flag;

        //// float deltaY = pegHeight - currHoop.transform.position.y;
        //float deltaY = pegHeight - toolTip.transform.position.y;
        //if (deltaY < 0.6f)
        //{
        //    // 2.1 Calculate the direction to move the arm in
        //    float directionY = -1f; // Since we always want to lower for drop
        //    // 1.2 Pass the new change in direction to the position vector
        //    Vector3 pos = new Vector3(0f, directionY * speedMultiplier, 0f);
            
        //    // collisionCont.SeparateBlockFromArm();
        //    // robotCont.MoveTip(pos * Time.deltaTime, armRotation, signal);
        //    robotCont.MoveTip(pos, armRotation, signal);
        //    armPosition = pos;
        //}

    }

    private bool RemoveHoopFromMapping()
    {
        foreach (var entry in pegNumberToHoopObjMapping)
        {
            int pegNumber = entry.Key;
            List<GameObject> hoopList = entry.Value;

            // Check if the list contains a GameObject with the same name as currHoop
            for (int i = 0; i < hoopList.Count; i++)
            {
                if (hoopList[i] != null && hoopList[i].name == currHoop.name)
                {
                    // Remove the GameObject from the list
                    hoopList.RemoveAt(i);
                    // Debug.Log($"Removed {currHoop.name} from peg {pegNumber}.");
                    return true;
                }
            }
        }
        return false;
    }


    ////////////////////////////////////

    // Reset the robot arm position

    /////////////////////////////////////

    /// <summary>
    /// Reset the arm location to the default position
    /// </summary>
    public void Reset()
    {
        robotCont.ResetTip();
    }

}
