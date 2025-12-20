using UnityEngine;
using UnityEditor;
using Unity.MLAgents.Sensors;
using Obi;
using System.Collections;

public class CutRopeAgent : BaseAgent
{
    [Header("Cut Rope References")]
    // Task Specific Environment References
    // See Parent for generic references
    public ObiSolver Solver;
    public GameObject RopePrefab;
    public GameObject RopeInstance;

    public GameObject ToolMidpoint;
    public GameObject Goal;
    public GameObject CutMarkerPrefab;

    [HideInInspector]
    public CutDetector CutDetector;

    enum CutRopeVariants { TwoDimensions, ThreeDimensions };
    [Header("Cut Rope Settings")]
    [SerializeField] CutRopeVariants Mode;
    public enum RewardMode { Sparse, SimpleDense, ComplexDense }
    public RewardMode rewardMode = RewardMode.Sparse;

    public float CutDistanceRewardScaling = 1.0f;
    public float HomeDistanceRewardScaling = 1.0f;
    public bool CollectJawSignalObservation = false;
    public int CollisionID = 0;


    public enum CutQuality { Bad, Good, Best };
    private CutQuality cutQuality = CutQuality.Bad;
    public enum CutRopeStatus {Cutting, CutStarted, CutFinished};
    private CutRopeStatus taskStatus = CutRopeStatus.Cutting;
    private int cutStartedStep = -1;
    private Vector3 cutStartedToolPosition = new Vector3(0f, 0f, 0f);
    private int goalElementIndex = 1;
    private ObiRope rope;
    private Vector3 originalPosition;
    private Quaternion originalRotation;
    private GameObject CutMarker1;
    private GameObject CutMarker2;
    private Vector3 originalCutMarkerScale;
    private Vector3 cutLocation;

    // NOTE: This is a convenience function. When a rope (or any Obi Actor spawns) the 
    // particles undergo some movement because they are suddenly exposed contraints to spawn,
    // so they need to find their relaxed/equilibrium state. The blueprint from the
    // relaxed state will actually avoid this, as particles start off at steady-state positions
    // To use this, just right click the script componenent during play mode and choose SaveBpState,
    // and it will generate a blueprint that you can add to the rope prefab over the existing bp.
#if UNITY_EDITOR
    [ContextMenu("SaveBpState")]
    void SaveBpState()
    {
        var passThisOne = Instantiate<ObiActorBlueprint>(rope.blueprint);
        rope.SaveStateToBlueprint(passThisOne);
        AssetDatabase.CreateAsset(passThisOne, "Assets/SavedRopeState.asset");
    }
#endif

    public override void Initialize()
    {
        base.Initialize();

        originalPosition = RopeInstance.transform.position;
        originalRotation = RopeInstance.transform.rotation;
        CutMarker1 = Instantiate<GameObject>(
            CutMarkerPrefab, ParentScene.transform);
        CutMarker2 = Instantiate<GameObject>(
            CutMarkerPrefab, ParentScene.transform);
        originalCutMarkerScale = CutMarker1.transform.localScale;

        CutDetector = Solver.GetComponent<CutDetector>();
        CutDetector.Agent = this;
    }

    private void LateUpdate()
    {
        UpdateCutMarkerPosition();
    }

    public override void EpisodeReset()
    {
        ResetFloor();
        ResetLight();
        ResetCamera();
        
        StartCoroutine(ResetRope());
        ResetToolColor();

        Vector3 toolStartPosition = new Vector3(
            RopeInstance.transform.localPosition.x,
            1.2f,
            RopeInstance.transform.localPosition.z);
        
        Vector3 toolStartRotation = new Vector3(0, 90, 180);
        if (Mode == CutRopeVariants.ThreeDimensions) toolStartRotation = new Vector3(0, 90, 180 + 45);

        ResetTool(0, toolStartPosition, toolStartRotation);
        taskStatus = CutRopeStatus.Cutting;
        cutStartedStep = -1;
        CutDetector.CutDetected = false;
    }

    private IEnumerator ResetRope()
    {
        rope = RopeInstance.GetComponent<ObiRope>();
        rope.RemoveFromSolver();

        Vector3 spawnPosition = new Vector3();
        if (Mode == CutRopeVariants.ThreeDimensions)
        {
            Vector2 spawnRangeX = new Vector2(
                -areaBounds.extents.x * DomainRandomizer.Instance.RandomizeDomain(
                    0f, "rope_spawn_range_x"),
                areaBounds.extents.x) * DomainRandomizer.Instance.RandomizeDomain(
                    0f, "rope_spawn_range_x");
            Vector2 spawnRangeZ = new Vector2(
                -areaBounds.extents.z * DomainRandomizer.Instance.RandomizeDomain(
                    0f, "rope_spawn_range_z"),
                areaBounds.extents.z * DomainRandomizer.Instance.RandomizeDomain(
                    0f, "rope_spawn_range_z"));

            spawnPosition = GetRandomSpawnPos(
                SpawnGround, spawnRangeX, spawnRangeZ);
            spawnPosition.y = originalPosition.y;
        }
        else if (Mode == CutRopeVariants.TwoDimensions)
        {
            spawnPosition = originalPosition;
        }

        RopeInstance.transform.position = spawnPosition;
        rope.ClearState();
        rope.AddToSolver();

        while (!rope.isLoaded)
            yield return new WaitForEndOfFrame();

        float thickness = DomainRandomizer.Instance.RandomizeDomain(
            rope.solver.principalRadii[0].x, "rope_thickness");

        for (int i = 0; i < rope.solverIndices.count; i++)
        {
            int solverIndex = rope.solverIndices[i];
            rope.solver.principalRadii[solverIndex] = new Vector3(
                thickness, thickness, thickness);
        }

        float norm_t = (thickness - 0.02f) / 0.02f;
        Vector3 cutMarkerScale = new Vector3(
            originalCutMarkerScale.x + (norm_t > 0 ? norm_t * 0.045f : norm_t * 0.035f),
            originalCutMarkerScale.y,
            originalCutMarkerScale.z + (norm_t > 0 ? norm_t * 0.045f : norm_t * 0.035f));

        rope.stretchingScale = DomainRandomizer.Instance.RandomizeDomain(
            rope.stretchingScale, "rope_sag");

        CutMarker1.transform.localScale = cutMarkerScale;
        CutMarker2.transform.localScale = cutMarkerScale;

        // Choose an edge (indexing the particles directly is not correct, there could be pooled/inactive particles)
        // Ignore the 3 edges on both sides to avoid the the cut marker being inside the mount
        goalElementIndex = Random.Range(4, rope.elements.Count - 4);

        // Use Collision Filtering per agent/env to get a small increase in performance
        int mask = (1 << CollisionID);
        var customFilter = ObiUtils.MakeFilter(mask, CollisionID);
        for (int i = 0; i < rope.solverIndices.count; ++i)
            rope.solver.filters[rope.solverIndices[i]] = customFilter;

        ObiCollider[] toolColliders = GetComponentsInChildren<ObiCollider>();
        for (int i = 0; i < toolColliders.Length; i++)
        {
            toolColliders[i].Filter = customFilter;
        }

        ObiCollider[] mountColliders = RopeInstance.GetComponentsInChildren<ObiCollider>();

        for (int i = 0; i < mountColliders.Length; i++)
        {
            mountColliders[i].Filter = customFilter;
        }

        Renderer[] renderers = RopeInstance.GetComponentsInChildren<Renderer>();

        Color newMarkerColor = DomainRandomizer.Instance.RandomizeColor(
            CutMarker1.GetComponent<Renderer>().material.color,
            "marker_r", "marker_g", "marker_b");
        CutMarker1.GetComponent<Renderer>().material.color = newMarkerColor;
        CutMarker2.GetComponent<Renderer>().material.color = newMarkerColor;

        if (DomainRandomizer.Instance.RandomizeDomain(0, "multicolor_rope_enabled") == 0.0f)
        {
            float ropeColor = DomainRandomizer.Instance.RandomizeDomain(
                renderers[0].material.color.r, "rope_r");
            renderers[0].material.color = new Color(ropeColor, ropeColor, ropeColor);
        }
        else
        {
            Color ropeColor = DomainRandomizer.Instance.RandomizeColor(
                renderers[0].material.color, "rope_r", "rope_g", "rope_b");
            renderers[0].material.color = ropeColor;
        }

        renderers[0].material.mainTextureScale = new Vector2(
            DomainRandomizer.Instance.RandomizeDomain(
                renderers[0].material.mainTextureScale.x,
                "x_tiling"),
            DomainRandomizer.Instance.RandomizeDomain(
                renderers[0].material.mainTextureScale.y,
                "y_tiling"));

        Color newMountColor = DomainRandomizer.Instance.RandomizeColor(
            renderers[1].material.color,
            "mount_r", "mount_g", "mount_b");
        for (int i = 1; i < renderers.Length; i++)
        {
            renderers[i].material.color = newMountColor;
        }
    }

    private void UpdateCutMarkerPosition()
    {
        if (taskStatus != CutRopeStatus.CutFinished)
        {
            // GetParticlePosition works in world space, direct indexing into positions[] is local solver space
            Vector3 firstParticlePosition = rope.GetParticlePosition(rope.elements[goalElementIndex].particle1);
            Vector3 secondParticlePosition = rope.GetParticlePosition(rope.elements[goalElementIndex].particle2);

            AlignCutMarker(CutMarker1.transform, firstParticlePosition, secondParticlePosition);
            AlignCutMarker(CutMarker2.transform, firstParticlePosition, secondParticlePosition);
        }
        else
        {
            AlignCutMarker(
                CutMarker1.transform,
                rope.GetParticlePosition(rope.elements[goalElementIndex].particle2),
                rope.GetParticlePosition(rope.elements[goalElementIndex].particle1));
            AlignCutMarker(
                CutMarker2.transform,
                rope.GetParticlePosition(rope.elements[goalElementIndex - 1].particle1),
                rope.GetParticlePosition(rope.elements[goalElementIndex - 1].particle2));
        }
    }

    private void AlignCutMarker(Transform objTransform, Vector3 pointA, Vector3 pointB)
    {
        Vector3 halfwayPoint = pointA + ((pointB - pointA) / 2f);
        if (taskStatus == CutRopeStatus.CutFinished)
        {
            halfwayPoint = halfwayPoint + ((pointB - halfwayPoint) / 2f);
        }
        objTransform.position = halfwayPoint;

        Vector3 dir = pointB - pointA;
        objTransform.rotation = Quaternion.LookRotation(dir);
        objTransform.localRotation *= Quaternion.Euler(-90, 0, 0);
    }

    public override void CollectObservations(VectorSensor sensor)
    {
        if (CollectJawSignalObservation)
        {
            sensor.AddObservation(Arms[0].controller.GetJawAngleRadians()); // (1)
        }

        if (UseVectorObservation)
        {
            sensor.AddObservation(
                CutMarker1.transform.position - ToolMidpoint.transform.position); // 3
            sensor.AddObservation(
                Goal.transform.position.y - ToolMidpoint.transform.position.y); // 1
            sensor.AddObservation(
                System.Convert.ToSingle(Arms[0].controller.GetJawAngleRadians())); // 1

            sensor.AddOneHotObservation(
                taskStatus == CutRopeStatus.CutStarted ? 1 : 0, 2); // 2
            sensor.AddOneHotObservation(
                taskStatus == CutRopeStatus.CutFinished ? 1 : 0, 2); // 2

            for (int i = 0; i < rope.elements.Count; i++)
            {
                var firstPos = rope.GetParticlePosition(
                    rope.elements[i].particle1);
                var secondPos = rope.GetParticlePosition(
                    rope.elements[i].particle2);

                sensor.AddObservation(ParentScene.transform.position - firstPos); // 3
                sensor.AddObservation(ParentScene.transform.position - secondPos); // 3
                sensor.AddObservation(ToolMidpoint.transform.position - firstPos); // 3
                sensor.AddObservation(ToolMidpoint.transform.position - secondPos); // 3
            } // 18 * 12 = 216
        }
    }

    public void CutDetectedCallback(int cutElementIndex, CutQuality quality)
    {
        if (taskStatus != CutRopeStatus.Cutting) return;

        if (cutElementIndex != goalElementIndex)
        {
            TaskFailure(-1.0f);
            return;
        }

        // Record the positions and step to check for successful cut behaviour
        cutQuality = quality;
        taskStatus = CutRopeStatus.CutStarted;
        cutStartedToolPosition = ToolMidpoint.transform.position;
        cutStartedStep = StepCount;

        // Adjust marker scale to make them half os long
        Vector3 markerScale = CutMarker1.transform.localScale;
        markerScale.y = markerScale.y / 2;
        CutMarker1.transform.localScale = markerScale;
        CutMarker2.transform.localScale = markerScale;

        // Calculate if the cut occured within 75% of the red marker zone
        // by projecting the tool midpoint onto the cut marker line
        Vector3 goalParticle1 = rope.GetParticlePosition(
            rope.elements[goalElementIndex].particle1);
        Vector3 goalParticle2 = rope.GetParticlePosition(
            rope.elements[goalElementIndex].particle2);
        float markerLength = Vector3.Distance(goalParticle1, goalParticle2);

        Vector3 projectedPoint = Vector3.Project(
            cutStartedToolPosition - goalParticle1,
            goalParticle2 - goalParticle1);

        projectedPoint += goalParticle1;

        if (Vector3.Distance(projectedPoint, goalParticle1) < markerLength * 0.25f || 
            Vector3.Distance(projectedPoint, goalParticle2) < markerLength * 0.25f)
        {
            cutQuality = CutQuality.Bad;
        }

        if (rewardMode != RewardMode.Sparse) return;
        AddReward(2f);
        reward += 2f;
    }

    public override void CheckEndConditions()
    {
        base.CheckEndConditions();

        if (CheckTaskEndCondition()) return;
        if (CheckCutEndConitions()) return;
    }

    public bool CheckCutEndConitions()
    {
        if (taskStatus != CutRopeStatus.CutStarted) return false;

        // To ensure that the jaw closes completely, we add a second reward on
        // jaw closing that must be within a few steps of the cut starting
        // Takes about 30 steps to close from a full open position if you set the command to be 0
        if ((StepCount - cutStartedStep) > 70)
        {
            TaskFailure(-1.0f);
            return true;
        }
        else if (Vector3.Distance(
            ToolMidpoint.transform.position, cutStartedToolPosition) > 0.05)
        {
            TaskFailure(-1.0f);
            return true;
        }
        else if (Arms[0].controller.GetJawAngleDegrees() < 0.1)
        {
            taskStatus = CutRopeStatus.CutFinished;
            if (rewardMode != RewardMode.Sparse) return true;
            AddReward(2f);
            reward += 2f;
            return true;
        }

        return false;
    }

    public bool CheckTaskEndCondition()
    {
        if (taskStatus != CutRopeStatus.CutFinished) return false;

        if (Vector3.Distance(
            ToolMidpoint.transform.position, Goal.transform.position) < 0.1)
        {
            TaskComplete(2.0f);
            return true;
        }

        return false;
    }

    public override void UpdateReward()
    {
        if (rewardMode == RewardMode.Sparse)
        {
            base.UpdateReward();
            return;
        }

        float negStepReward = -(float)StepCount / (float)MaxStep;
        float cutProgress = 0f;
        float homeProgress = 0f;
        float sparseCutReward = 0f;

        if (taskStatus == CutRopeStatus.Cutting)
        {
            float exp_scaling = 4.0f;
            // if (Mode == CutRopeVariants.ThreeDimensions) exp_scaling = 2.0f;
            cutProgress = AgentHelper.ExpDistanceReward(
                ToolMidpoint.transform.position,
                CutMarker1.transform.position,
                0.0f, 100f, exp_scaling);

            // Keep track of cut marker location to use for homing
            cutLocation = ToolMidpoint.transform.position;
        }
        else
        {
            cutProgress = 1.0f;
            homeProgress = Vector3.Distance(
                ToolMidpoint.transform.position, Goal.transform.position);
            homeProgress = 1 - (
                homeProgress / Vector3.Distance(Goal.transform.position, cutLocation));
        }

        cutProgress *= CutDistanceRewardScaling;
        homeProgress *= HomeDistanceRewardScaling;

        if (taskStatus == CutRopeStatus.CutStarted) sparseCutReward = 1.0f;
        if (taskStatus == CutRopeStatus.CutFinished) sparseCutReward = 2.0f;
        
        if (rewardMode == RewardMode.ComplexDense)
        {
            switch (cutQuality)
            {
                case CutQuality.Bad:
                    break;
                case CutQuality.Good:
                    sparseCutReward *= 2;
                    break;
                case CutQuality.Best:
                    sparseCutReward *= 4;
                    break;
                default:
                    break;
            }
        }

        float current_reward = negStepReward + cutProgress + 
            sparseCutReward + homeProgress;
        AddReward(current_reward - reward);
        reward = current_reward;
    }
}
