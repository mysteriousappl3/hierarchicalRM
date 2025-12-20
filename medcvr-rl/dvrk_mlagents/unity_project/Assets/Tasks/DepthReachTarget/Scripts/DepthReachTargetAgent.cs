using UnityEngine;
using Unity.MLAgents.Sensors;
using Unity.MLAgents.Actuators;

public class DepthReachTargetAgent : BaseAgent
{
    [Header("DepthReachTarget References and Settings")]
   
    public GameObject Goal;
    public GameObject Cylinder;

    [HideInInspector]
    public CollisionStayDetect CylinderCollisionDetect;
    [HideInInspector]
    public CollisionStayDetect GroundCollisionDetect;

    public float ProgressRewardShaping = 1.0f;
    public float DistanceRewardShaping = 1.0f;

    public float OptimalDistanceFromSurface = 0.1f;
    
    private Vector3 startTipPosition;
    private float cylinderRadius;
    public override void Initialize()
    {
      
        base.Initialize();

        CylinderCollisionDetect = Cylinder.GetComponent<CollisionStayDetect>();
        CylinderCollisionDetect.Agent = this;

        GroundCollisionDetect = SpawnGround.GetComponent<CollisionStayDetect>();
        GroundCollisionDetect.Agent=this;

        EpisodeReset();
    }

    public override void EpisodeReset()
    {
        base.EpisodeReset();
        ResetCylinder();

        float randX = DomainRandomizer.Instance.RandomizeDomain(0.0f, "tool_position_noise_x");

        Vector3 randomStartPos = ParentScene.transform.position + new Vector3(randX, 0.5f, 1.77f);
        ResetArm(0, randomStartPos);
        startTipPosition = randomStartPos;

        Color newGoalColor = DomainRandomizer.Instance.RandomizeColor(
            Goal.GetComponent<Renderer>().material.color,
            "target_rb", "target_g", "target_rb");
        Goal.GetComponent<Renderer>().material.color = newGoalColor;
    }

    public void ResetCylinder()
    {
        // float new_height = DomainRandomizer.Instance.RandomizeDomain(Cylinder.transform.localScale.z, "cylinder_h");
       
        // float new_radius = (float) (0.5 * ((6.25 / new_height) + new_height));
 
        // float new_y_position = (float) (0.5 * (( 6.25 / new_height) - new_height));

        // Vector3 pos = Cylinder.transform.position;
        // Cylinder.transform.position = new Vector3(pos.x, new_y_position, pos.z);

        // Vector3 scale = Cylinder.transform.localScale;
        // Cylinder.transform.localScale = new Vector3(new_radius, scale.y, new_height);

        cylinderRadius = Cylinder.transform.localScale.x / 2;
                            
        Color newCylinderColor = DomainRandomizer.Instance.RandomizeColor(
            Cylinder.GetComponent<Renderer>().material.color,
            "cylinder_r", "cylinder_g", "cylinder_b");
        Cylinder.GetComponent<Renderer>().material.color = newCylinderColor;
    }

    public override void CheckEndConditions()
    {
        CheckDistanceToGoal();
    }

    public void CheckDistanceToGoal()
    {
        if (Vector3.Distance(ToolTip.transform.position, Goal.transform.position) < 0.1)
        {
            TaskComplete(2.0f);
        }
    }

    public void AddBoundaryPenalty()
    {
        AddReward(-0.25f);
        reward += (-0.25f);
    }

    public override void CollectObservations(VectorSensor sensor)
    {
        if (UseVectorObservation)
        {
            sensor.AddObservation(Goal.transform.position - ToolTip.transform.position);
            sensor.AddObservation(Cylinder.transform.position - ToolTip.transform.position);
            sensor.AddObservation(Cylinder.transform.position - Goal.transform.position);
        }
    }

    public override void UpdateReward()
    {

        float negStepReward = -(float)StepCount / (float)MaxStep;
        
        // TODO: Change this to be only in the z direction?
        float progressReward = Vector3.Distance(ToolTip.transform.position, Goal.transform.position);
        progressReward = 1 - (progressReward / Vector3.Distance(Goal.transform.position, startTipPosition));


        float distanceToGround = ToolTip.transform.position.y - SpawnGround.transform.position.y;
        Vector3 tipProjectedOnCylinder = Vector3.Project(ToolTip.transform.position - Cylinder.transform.position, Cylinder.transform.up);

        float distanceToCylinderCenter = Vector3.Distance(ToolTip.transform.position, (Cylinder.transform.position + tipProjectedOnCylinder));
        float distanceToCylinderSurface = distanceToCylinderCenter - cylinderRadius;

        float closestDistance = Mathf.Min(distanceToGround, distanceToCylinderSurface);
        closestDistance = Mathf.Abs(closestDistance - OptimalDistanceFromSurface);

        float distanceReward = Mathf.Exp(-closestDistance);

        progressReward *= ProgressRewardShaping;
        distanceReward *= DistanceRewardShaping;

        float current_reward = negStepReward + progressReward + distanceReward;
        AddReward(current_reward - reward);
        reward = current_reward;
    }


}

