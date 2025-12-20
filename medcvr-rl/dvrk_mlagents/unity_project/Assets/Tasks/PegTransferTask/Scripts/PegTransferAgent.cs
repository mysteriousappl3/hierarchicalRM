using UnityEngine;
using Unity.MLAgents.Actuators;
using System;

public class PegTransferAgent : BaseAgent
{
    public GameObject blockPeg;
    public GameObject goalPeg;

    [SerializeField]
    private Transform blockTransform;

    private GameObject goal;
    public Vector3 goalPosition;

    private JawCollision collisionController;
    private UrdfJointController urdfController;

    public  GameObject prefab;
    private GameObject block;
    public Vector3 blockPosition;
    private Quaternion blockRotation;

    // Points to the sphere object on the side of the block indicating ideal grab location
    // private Vector3 grabPosition;
    private GameObject gripper;

    private Transform topMostParent;

    public bool blockGrabbed;
    public bool escapedStartPeg;
    public float escapePegReward = 0f;

    public float distRewardScaling;
    public float heightRewardScaling;
    public float lowerBlockRewardScaling;

    private float maxPegHeight;
    private float maxDistanceToPeg;

    public enum RewardMode { Sparse, Dense }
    public RewardMode rewardMode = RewardMode.Dense;

    public enum BehaviourMode { RL, API }
    public BehaviourMode behaviourMode = BehaviourMode.RL;

    public float blockGrabReward = 0f;

    public void Start()
    {
        GameObject robot = GameObject.FindWithTag("robot");
        urdfController = robot.GetComponent<UrdfJointController>();

        goal = GameObject.Find("GoalTrigger");
        goalPosition = goal.transform.position;
        goalPeg = GameObject.Find("goal_peg");

        topMostParent = GetTopMostParent(transform);
        blockTransform = topMostParent.Find("Hoop").transform;
        // grabPosition = blockTransform.Find("PickLocation").transform.position;
        gripper = GameObject.Find("tool_gripper2_link");
        collisionController = gripper.GetComponent<JawCollision>();

        block = blockTransform.gameObject;
        blockPosition = block.transform.localPosition;
        blockRotation = block.transform.localRotation;

        blockGrabbed = false;
        escapedStartPeg = false;
        distRewardScaling = 3f; 
        heightRewardScaling = 1.5f;
        lowerBlockRewardScaling = 3f;

        Vector3 goalPegPos = goalPeg.transform.position;
        Vector3 flatGoalPegPosition = new Vector3(goalPegPos.x, 0, goalPegPos.z);
        Vector3 flatBlockPosition = new Vector3(blockTransform.position.x, 0, blockTransform.position.z);

        maxDistanceToPeg = Vector3.Distance(flatGoalPegPosition, flatBlockPosition);
        maxPegHeight = goalPeg.transform.position.y;
    }

    Transform GetTopMostParent(Transform child)
    {
        while (child.parent != null)
        {
            child = child.parent;
        }
        return child;
    }

    public Transform GetBlockTransform() { return blockTransform; }

    public override void Initialize()
    {
        base.Initialize();
        
    }

    public override void EpisodeReset()
    {
        if (behaviourMode == BehaviourMode.RL)
        {
            base.EpisodeReset();
            collisionController.objectGrabbed = false;
            collisionController.otherJaw.objectGrabbed = false;
            collisionController.pickedBlockOnce = false;
            collisionController.otherJaw.pickedBlockOnce = false;
            collisionController.isColliding = false;
            collisionController.otherJaw.isColliding = false;

            blockGrabReward = 0f;
            escapePegReward = 0f;
            blockGrabbed = false;
            escapedStartPeg = false;
            ResetGoalAndObstacle();
            ResetArm(0);
            ResetBlock();
        }
    }

    public void ResetBlock()
    {

        Rigidbody blockRB = block.GetComponent<Rigidbody>();
        if (blockRB != null)
        {
            blockRB.angularVelocity = Vector3.zero;
            blockRB.linearVelocity = Vector3.zero;
        }
        block.transform.position = blockPosition;
        block.transform.rotation = blockRotation;
    }

    public void ResetGoalAndObstacle()
    {
        // Unattach the object from the robot arm if previously attached
        collisionController.SeparateBlockFromArm();
        
    }

    public override void GoalTriggerCallback()
    {
        TaskComplete(5.0f); // Keep rewards between +1 to +5 and not too large
        Debug.Log("Task Completed with cumulative reward = " + GetCumulativeReward());

    }

    public override void PenaltyTriggerCallback()
    {
        // Agent stayed in penalty zone for too long
        TaskFailure(-2.5f);
    }

    public override void Heuristic(in ActionBuffers actionsOut)
    {
        AddInputToActionBuffers(actionsOut, Input.GetAxis("Horizontal"), "position_x");
        AddInputToActionBuffers(actionsOut, Input.GetAxis("Vertical"), "position_y");
        AddInputToActionBuffers(actionsOut, Input.GetAxis("UpDown"), "position_z");
        AddInputToActionBuffers(actionsOut, Arms[0].jawOpen ? 1f : -1f, "jaw");
    }

    public void GrabBlockReward()
    {
        blockGrabbed = true;
        blockGrabReward = 2.5f;
        // AddReward(blockGrabReward);  // Dont add here since we do the calculation in currReward under UpdateReward()
    }

    public void EscapePegReward()
    {
        escapedStartPeg = true;
        escapePegReward = 1f;
        // AddReward(escapePegReward);  // Dont add here since we do the calculation in currReward under UpdateReward()
    }

    public void DropBlockPenalty()
    {
        TaskFailure(-2.5f);
    }

    public override void UpdateReward()
    {
        float negStepReward = -(float)StepCount / (float)MaxStep;
        
        if (rewardMode == RewardMode.Sparse)
        {
            base.UpdateReward();
            return;
        }
        // Phase 1 - Reach Block
        float reachBlockReward = 0f;
        // Phase 2 - Lift Block to Goal
        float distReward = 0f;
        float heightReward = 0f;
        float holdBlockReward = 0f;
        // Phase 3 - Lower the block into the peg
        float lowerBlockReward = 0f;

        // EDIT: Since we use a hollow hoop, any location is optimal grab location
        //// Phase 1 Reward - Calculate distance to grab location
        //if (urdfController.GetJawOpen() &&
        //    (!collisionController.objectGrabbed && !collisionController.otherJaw.objectGrabbed))
        //{
        //    Vector3 gripperPos = gripper.transform.position;
        //    float distToGrabLoc = Vector3.Distance(grabPosition, gripperPos);
        //    float jawGrabLocReward = Mathf.Clamp(1f - distToGrabLoc, 0f, 1f);
        //    reachBlockReward = jawGrabLocReward;
        //}

        // Phase 2 Reward (i) - Distance from goal peg
        Vector3 goalPegPos = goalPeg.transform.position;
        Vector3 flatGoalPegPosition = new Vector3(goalPegPos.x, 0, goalPegPos.z);
        Vector3 flatBlockPosition = new Vector3(blockTransform.position.x, 0, blockTransform.position.z);

        float distance = Vector3.Distance(flatGoalPegPosition, flatBlockPosition);
        distReward = Mathf.Clamp(maxDistanceToPeg - distance, 0f, maxDistanceToPeg) * distRewardScaling;

        // Phase 2 Reward (ii) - Height of block and goal peg
        Collider blockCollider = GameObject.FindWithTag("OuterEdgeCollider").GetComponent<Collider>();
        float blockBottomY = blockCollider.bounds.min.y;
        float heightDiff = Mathf.Abs(goalPegPos.y - blockBottomY);
        heightReward = Mathf.Clamp(maxPegHeight - heightDiff, 0f, maxPegHeight) * heightRewardScaling;

        // Commented since once gabbed block can't be dropped
        // if ((collisionController.objectGrabbed || collisionController.otherJaw.objectGrabbed) &&
        //     !urdfController.GetJawOpen())
        // {

            //     // Agent has kept it's jaw closed and is grabbing the object so give it a positive reward
            //     holdBlockReward = 1f;
            // }

        // Add penalty if agent drops the block after grabbing it which calls TaskFailure
        if (urdfController.GetJawOpen() && (distance > 0.14f) &&
             (!collisionController.objectGrabbed || !collisionController.otherJaw.objectGrabbed) &&
             (collisionController.pickedBlockOnce || collisionController.otherJaw.pickedBlockOnce))
        {
            DropBlockPenalty();
        }

        // float currReward = negStepReward + distReward + heightReward +
        //     reachBlockReward + blockGrabReward + holdBlockReward + escapePegReward;

        // (Phase 1 - Reach Block) + (Phase 2 - Lift Block to Goal)
        /*
            NOTE: Once the agent has grabbed the block, it should continue to get the max block reward of 4f instead of mapping it to 0f in previous approach.
            Previously, since the block is only grabbed once, the large 4f reward is only given once and then the reward doesn't account for 4f reward so agent essentially forgets the grabbed progress
            and reaches a suboptimal policy of grabbing block and hovering around there.
        */
        float currReward = negStepReward;
        //if (blockGrabbed)
        //{
        //    currReward += (reachBlockReward + 4f) + (distReward + heightReward + holdBlockReward + escapePegReward);
        //}
        //else
        //{   // blockGrabReward is 0f until agent grabs the block.
        //    // currReward += (reachBlockReward + blockGrabReward) + (distReward + heightReward + holdBlockReward + escapePegReward);
        //}


        // Phase 3 Reward - Check if block is within a distance to begin lowering to complete the task
        // The height criteria checks if block is inside the peg within a small epsilon.
        if (distance <= 0.14f && (goalPegPos.y >= 0.04f + blockCollider.bounds.max.y))
        {
            /*
                Note: Since the agent is now trying to lower it's height, the heightReward which depends on the tip of the peg
                will decrease. The agent at this stage is met all the requirements for phase 1 and 2 rewards so we need to ensure
                these remain constant since otherwise as it lowers, the heightReward is going to be less than the peak value it found
                and increasing lowerBlockReward doesn't make up for the difference. Hence why we add the maxHeight as the reward below.
             */
            float maxHeightReward = maxPegHeight * heightRewardScaling;
            float maxDistReward = maxDistanceToPeg * distRewardScaling;

            float blockToGoalHeightDiff = Mathf.Abs(goalPosition.y - blockBottomY);
            lowerBlockReward = Mathf.Exp(-blockToGoalHeightDiff) * lowerBlockRewardScaling;
            currReward += (blockGrabReward) + (maxDistReward + maxHeightReward + escapePegReward) + (lowerBlockReward);
        }
        else
        {
            currReward += (blockGrabReward) + (distReward + heightReward + escapePegReward);
        }

        AddReward(currReward - reward);
        reward = currReward;
        
    }

    public override void OnEpisodeBegin()
    {
        base.OnEpisodeBegin();

        GameObject block = blockTransform.gameObject;
        if (block.GetComponent<Rigidbody>() == null)
        {
            block.AddComponent<Rigidbody>();
            block.GetComponent<Rigidbody>().mass = 0.1f;
        }
    }

    //// For now, disabled the ability to drop the block once grabbed
    //public override void OnActionReceived(ActionBuffers actionBuffers)
    //{
    //    base.OnActionReceived(actionBuffers);

    //    int jawAction = actionBuffers.DiscreteActions[0];

    //    urdfController.SetJawOpen(Convert.ToBoolean(jawAction));
    //}
}
