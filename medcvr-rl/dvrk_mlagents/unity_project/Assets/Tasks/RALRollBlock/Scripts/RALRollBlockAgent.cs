using UnityEngine;
using Unity.MLAgents.Actuators;

using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;
using System.Collections.Generic;


public class RollBlockExperiment
{
    public int setNumTriesPerGrid;
    public int numTriesPerGridCount = 0;
    public int currentGridIdx = 0;
    public new List<Vector3> blockGridLocations;
    public new List<int> numRollResults;
};

public class RALRollBlockAgent : BaseAgent
{
    public GameObject Block;
    private GameObject m_blockSides;
    private Rigidbody blockBody;
    private float blockSizeCutoffDistance; // Cutoff distance at circle corner of block
    private int blockAxisIndex;

    public GameObject Goal;
    private GoalTrigger GoalDetect;
    private GoalPenaltyTrigger goalPenaltyDetect;
    public GameObject GroundGroup;
    public GameObject TopCamera; // Optional
    public GameObject GlobalVolume; //Optional
    private Vignette vignette; // For Vignette

    public bool IsExperiment = false;
    private RollBlockExperiment rollBlockExperiment;

    private bool firstReset = true;
    public bool UseLookAtCamera = false;
    public float LessThanPointFiveNoShadow = 0.0f;
    // Roll detection
    private int countRoll = 0;
    public bool EndEpisodeOnMaxRolls = false;
    public bool EndEpisodeOnToolMovingBack = false;
    private bool maxRollsFinished = false;

    // Rewards
    public bool useDenseRewards = true;
    public float LifetimePenaltyScale = 1.00f; // Total penalty at MaxSteps. TODO, should also work when useDenseRewards = false, but no
    public int MaxRollsForReward = -1; // if -1, then no maximum rolls.
    public float PerRollRewardScale = 1.25f;
    // public float DistanceYRewardShaping = 5.0f; // Height y needs to be very sensitive
    // public float DistanceXZRewardShaping = 1.0f;
    // public float DistanceRewardYScale = 0.333f;
    // public float DistanceRewardXZScale = 0.667f;
    public float DistanceRewardShaping = 1.0f;
    public float DistanceRewardScale = 1f;
    public float LeftOfCubeRewardScale = 0.5f;
    private float degTolLeftOfCube = 7f; // (Tested) When rolling, the angle can go up to 110 even if it should be above z normal?
    [HideInInspector]
    public bool isToolLeftofBlock = true;

    public bool LogRewardsDebug = false;
    private float totalDenseReward = 0.0f;
    private float m_totalPenalties = 0.0f;

    // Data for tip must be in the positive surface plane closest pointing to z axis of ground group
    // ie. LeftOfCubeReward
    private Mesh blockMesh;
    private int zNormalTriangleIdx;
    private SortedSet<int> zNormalCornerVertices = new SortedSet<int>();

    public override void Initialize()
    {
        base.Initialize();
        Physics.gravity = new Vector3(0, -9.8f * 20f, 0);
        blockBody = Block.GetComponent<Rigidbody>();
        MeshFilter mf = Block.GetComponent<MeshFilter>();
        blockMesh = mf.mesh;

        GoalDetect = Block.GetComponent<GoalTrigger>();
        goalPenaltyDetect = Block.GetComponent<GoalPenaltyTrigger>();
        if (GoalDetect)
        {
            GoalDetect.Agent = this;
        }
        else if (goalPenaltyDetect)
        {
            goalPenaltyDetect.Agent = this;
        }

        var htpt = Block.GetComponent<HitTopPenaltyTrigger>();
        if (htpt)
        {
            htpt.Agent = this;
        }

        var groundPenaltyTrigger = Ground.GetComponent<GroundPenaltyTrigger>();
        if (groundPenaltyTrigger)
        {
            groundPenaltyTrigger.Agent = this;
        }

        if (GlobalVolume)
        {
            Volume volume = GlobalVolume.GetComponent<Volume>();
            volume.profile.TryGet(out vignette);
            if (!vignette)
            {
                Debug.Log("Global volume set, but no vignette found, not using");
            }
        }
        // m_blockSides = Block.transform.GetChild(0).gameObject;
        // Debug.Log(m_blockSides.transform.localScale);
        // Debug.Log("Tool tip");
        // Debug.Log(ToolTip.transform.position);
        // Debug.Log("Block");
        // Debug.Log(Block.transform.position);
        if(IsExperiment)
        {
            rollBlockExperiment = new RollBlockExperiment();
            rollBlockExperiment.setNumTriesPerGrid = 1;
            rollBlockExperiment.numTriesPerGridCount = 0;
            rollBlockExperiment.currentGridIdx = 0;
            rollBlockExperiment.numRollResults = new List<int>();

            float blockHeight = Block.transform.localScale.y / 2;
            // Relative spawn ground
            rollBlockExperiment.blockGridLocations = new List<Vector3>()
                {
                    new Vector3(0.01f, blockHeight, -0.01f),
                    new Vector3(-0.01f, blockHeight, -0.01f)
                };
        }
    }

    public override void OnEpisodeBegin()
    {
        totalDenseReward = 0.0f;
        base.OnEpisodeBegin(); // Will do ResetPSMandTip and will do again second time in EpisodeReset()
    }

    private void ResetBlockPresetAndToolBehindIt()
    {
        Block.transform.localPosition = rollBlockExperiment.blockGridLocations[rollBlockExperiment.currentGridIdx];
        Vector3 tip_position_wrt_world = Block.transform.position;
        tip_position_wrt_world.y += Block.transform.localScale.y / 2; // on top surface of block
        tip_position_wrt_world.z += 0.007f * 20f; // 0.14
        tip_position_wrt_world.y += DomainRandomizer.Instance.RandomizeDomain(0.0f, "tool_position_noise_y"); 
        ResetArm(0, tip_position_wrt_world);
    }

    private void PrivateEpisodeReset()
    {
        ResetFloor();
        ResetPsmBase();
        ResetLight();
        ResetLightShadow();
        ResetTopCamera();
        ResetGroundInclination();
        ResetVignette();
        if(!IsExperiment)
        {
            ResetBlock();
            if (UseLookAtCamera)
                ResetLookAtBlockCamera();
            else
                ResetCamera();
            ResetGoal();
            ResetPsmTipBehindBlock();
        }
        else// experiment
        {
            ResetBlockPresetAndToolBehindIt();
        }
        countRoll = 0;
        maxRollsFinished = false;
        // Rolling Data
        findNormalandCenterOfZFacingSurface(
            ref zNormalTriangleIdx,
            ref zNormalCornerVertices);
        blockAxisIndex = findUpBlockAxisIndex();
    }
    public override void EpisodeReset()
    {
        PrivateEpisodeReset();
        // bool properReset = TestBlockAndToolVisable();
        // int count = 1;
        // while(!properReset && !firstReset)
        // {
        //     PrivateEpisodeReset();
        //     properReset = TestBlockAndToolVisable();
        //     Debug.LogWarning("Resetting: " + count);
        //     count++;
        // }
        firstReset = false;
    }

    bool TestVector3WithinFrustrumPlanes (Plane[] planes, Vector3 position)
    {
        foreach (var plane in planes)
        {
            if (plane.GetDistanceToPoint(ToolTip.transform.position) < 0)
                return false;
        }
        return true;
    }

    bool TestViewPort(Camera cam, Vector3 position)
    {
        Vector3 v = cam.WorldToViewportPoint(position);
        if(v.x < 0f || v.x > 1.0f || v.y < 0f || v.y > 1.0f) return false;
        return true;
    }

    bool TestBlockAndToolVisable()
    {
        if(!SceneCamera) return true;
        Camera cam = SceneCamera.GetComponent<Camera>();

        // Plane[] planes = GeometryUtility.CalculateFrustumPlanes(SceneCamera.GetComponent<Camera>());
        if(!TestViewPort(cam, ToolTip.transform.position))
        {
            Debug.LogWarning("Tool tip transform not in view of camera");
            return false;
        }
        Vector3[] vertices = blockMesh.vertices;
        foreach(var v in vertices)
        {
            Vector3 v_wrt_world = Vector3.Scale(Block.transform.rotation * v, Block.transform.localScale) + Block.transform.position;
            if(!TestViewPort(cam, v_wrt_world))
            {
                Debug.LogWarning("One of the Block vertices not in view of camera");
                return false;
            }
        }
        return true;
    }

    void ResetPsmBase()
    {
        // Doesn't work ?? Use Ground px py pz instead
        Vector3 psmBaseNoise = DomainRandomizer.Instance.RandomizeVec3(
                Vector3.zero, "psm_px_noise", "psm_py_noise", "psm_pz_noise");
        this.transform.position = this.transform.position + psmBaseNoise;

        Vector3 psmBaseEulerAnglesNoise =  DomainRandomizer.Instance.RandomizeVec3(
            Vector3.zero, "psm_rx_noise", "psm_ry_noise", "psm_rz_noise");
        this.transform.localEulerAngles = this.transform.localEulerAngles + psmBaseEulerAnglesNoise;

    }

    void ResetLookAtBlockCamera()
    {
        if (SceneCamera)
        {
            SceneCamera.transform.localPosition = DomainRandomizer.Instance.RandomizeVec3(
                SceneCamera.transform.localPosition, "camera_px", "camera_py", "camera_pz");
            SceneCamera.transform.LookAt(Block.transform);

            Vector3 eulerAnglesNoise =  DomainRandomizer.Instance.RandomizeVec3(
                Vector3.zero, "camera_rx_noise", "camera_ry_noise", "camera_rz_noise");
            SceneCamera.transform.localEulerAngles = SceneCamera.transform.localEulerAngles + eulerAnglesNoise;
        }
    }

    void ResetLightShadow()
    {
        if (SceneLight)
        {
            float val = DomainRandomizer.Instance.RandomizeDomain(LessThanPointFiveNoShadow, "less_than_point_five_no_shadow");
            if(val > 0.5f)
                SceneLight.shadows = LightShadows.Soft;
            else //val < 0.5
                SceneLight.shadows = LightShadows.None;
        }
    }
    void ResetGroundInclination()
    {
        GroundGroup.transform.localPosition = DomainRandomizer.Instance.RandomizeVec3(
                GroundGroup.transform.localPosition, "ground_px", "ground_py", "ground_pz");

        GroundGroup.transform.localEulerAngles = DomainRandomizer.Instance.RandomizeVec3(
                GroundGroup.transform.localEulerAngles, "ground_angle_x", "ground_angle_y", "ground_angle_z");

    }

    protected void ResetTopCamera()
    {
        if (TopCamera)
        {
            TopCamera.transform.localPosition = DomainRandomizer.Instance.RandomizeVec3(
                TopCamera.transform.localPosition, "top_camera_px", "top_camera_py", "top_camera_pz");

            TopCamera.transform.localEulerAngles = DomainRandomizer.Instance.RandomizeVec3(
                TopCamera.transform.localEulerAngles, "top_camera_rx", "top_camera_ry", "top_camera_rz");
        }
    }

    protected void ResetVignette()
    {
        if (vignette)
        {
            vignette.intensity.value = DomainRandomizer.Instance.RandomizeDomain(vignette.intensity.value, "vignette_intensity");
        }
    }

    void ResetBlock()
    {
        Block.transform.localScale = DomainRandomizer.Instance.RandomizeVec3(
                Block.transform.localScale, "block_scale_x", "block_scale_y", "block_scale_z");

        float padding = 1.10f; // Distance reward padding
        float block_y = Block.transform.localScale.y * padding;
        float block_z = Block.transform.localScale.z * padding;
        blockSizeCutoffDistance = Mathf.Sqrt(
            block_y * block_y +
            block_z * block_z) / 2;

        // Location
        var spawn_extents_x = DomainRandomizer.Instance.RandomizeDomain(areaBounds.extents.x, "spawn_extents_x");
        var spawn_extents_z = DomainRandomizer.Instance.RandomizeDomain(areaBounds.extents.z, "spawn_extents_z");
        // Debug.Log(areaBounds.extents.x);
        // Debug.Log(areaBounds.extents.z);
        Block.transform.localPosition = GetRandomSpawnPosRelativeGroundGroup(
            Block,
            new Vector2(-spawn_extents_x, spawn_extents_x),
            new Vector2(-spawn_extents_z, spawn_extents_z));

        // Rotation
        Block.transform.rotation = new Quaternion();
        float euler_y = DomainRandomizer.Instance.RandomizeDomain(Block.transform.localEulerAngles.y, "block_euler_y");
        float rand_euler_y = Random.Range(-euler_y, euler_y);
        Block.transform.localEulerAngles = new Vector3(0.0f, rand_euler_y, 0.0f);

        // Mass, damping, friction
        blockBody.mass = DomainRandomizer.Instance.RandomizeDomain(blockBody.mass, "block_mass");
        blockBody.linearVelocity = Vector3.zero;
        blockBody.angularVelocity = Vector3.zero;

        var BlockCollider = Block.GetComponent<Collider>();
        // Assumes same value for both static and dynamic friction
        var block_friction = DomainRandomizer.Instance.RandomizeDomain(BlockCollider.material.dynamicFriction, "block_friction");
        BlockCollider.material.dynamicFriction = block_friction;
        BlockCollider.material.staticFriction = block_friction;

        // Block color
        float H, S, blockColorV;
        Color.RGBToHSV(Block.GetComponent<Renderer>().material.color, out H, out S, out blockColorV);
        blockColorV = DomainRandomizer.Instance.RandomizeDomain(blockColorV, "block_color_v");
        Block.GetComponent<Renderer>().material.color = Color.HSVToRGB(0f, 0f, blockColorV);

        // m_blockSides.GetComponent<Renderer>().material.color =
        //     DomainRandomizer.Instance.RandomizeColor(
        //         m_blockSides.GetComponent<Renderer>().material.color,
        //         "block_side_color_r", "block_side_color_g", "block_side_color_b");
    }

    void ResetPsmTipBehindBlock()
    {
        Vector3 tip_position_wrt_world = Block.transform.position;
        tip_position_wrt_world.y += Block.transform.localScale.y / 2; // on top surface of block
        // tip_position_wrt_world.z += 0.00746f * 20f + Block.transform.localScale.z / 2; // 0.15 behind the block

        tip_position_wrt_world.z += 0.007f * 20f; // 0.14

        tip_position_wrt_world.x += DomainRandomizer.Instance.RandomizeDomain(0.0f, "tool_position_noise_x"); 
        tip_position_wrt_world.y += DomainRandomizer.Instance.RandomizeDomain(0.0f, "tool_position_noise_y"); 
        tip_position_wrt_world.z += DomainRandomizer.Instance.RandomizeDomain(0.0f, "tool_position_noise_z"); 

        ResetArm(0, tip_position_wrt_world);
    }

    void ResetGoal()
    {
        float H, S, goalColorV;
        Color.RGBToHSV(Goal.GetComponent<Renderer>().material.color, out H, out S, out goalColorV);
        goalColorV = DomainRandomizer.Instance.RandomizeDomain(goalColorV, "goal_color_v");
        Goal.GetComponent<Renderer>().material.color = Color.HSVToRGB(0f, 0f, goalColorV);
        //Goal.transform.localPosition = DomainRandomizer.Instance.RandomizeVec3(
        //        Goal.transform.localPosition, "goal_px", "goal_py", "goal_pz");
    }

    private void LogDebugVector3(Vector3 vec)
    {
        Debug.Log(vec.x + ", " + vec.y + ", " + vec.z);
    }

    private void findNormalandCenterOfZFacingSurface(ref int z_normal_triangle_idx, ref SortedSet<int> corners)
    {
        Vector3[] normals = blockMesh.normals;
        int[] triangles = blockMesh.triangles;
        // --- Find two normal facing z ground group
        int idx_1 = -1;
        float current_angle_1 = 1000;
        Vector3 normal_1 = new Vector3(0, 0, 0);
        int idx_2 = -1;
        float current_angle_2 = 1000;
        Vector3 normal_2 = new Vector3(0, 0, 0);;

        Vector3 z_vec = new Vector3(0f, 0f, 1f);
        for (int i = 0; i < triangles.Length; i = i + 3)
        {
            var normal_wrt_parent = Block.transform.localRotation * normals[triangles[i]];
            float angle = Vector3.Angle(normal_wrt_parent, z_vec);
            if(angle < current_angle_2)
            {
                current_angle_2 = angle;
                idx_2 = i;
                normal_2 = normal_wrt_parent;
                if(current_angle_2 < current_angle_1)
                {
                    // swap
                    int temp_idx = idx_1;
                    float temp_angle = current_angle_1;
                    Vector3 temp_normal = normal_1;
                    idx_1 = idx_2;
                    current_angle_1 = current_angle_2;
                    normal_1 = normal_2;
                    idx_2 = temp_idx;
                    current_angle_2 = temp_angle;
                    normal_2 = temp_normal;
                }
            }
        }
        z_normal_triangle_idx = idx_1;

        // Remove repeated vertices
        corners.Clear();
        corners.Add(triangles[idx_1]);
        corners.Add(triangles[idx_1 + 1]);
        corners.Add(triangles[idx_1 + 2]);
        corners.Add(triangles[idx_2]);
        corners.Add(triangles[idx_2 + 1]);
        corners.Add(triangles[idx_2 + 2]);
    }

    private void getNormalandCenter(ref Vector3 z_surface_normal_wrt_world, ref Vector3 z_surface_center_wrt_world, int z_normal_triangle_idx, SortedSet<int> corners)
    {
        // Surface Normal
        z_surface_normal_wrt_world = Block.transform.rotation * blockMesh.normals[blockMesh.triangles[z_normal_triangle_idx]];
        // Center
        Vector3[] vertices = blockMesh.vertices;
        Vector3 center_vertice = new Vector3(0,0,0);
        int count = 0;
        foreach(var s in corners)
        {
            center_vertice = center_vertice + vertices[s];
            count++;
        }
        center_vertice = center_vertice/count;
        z_surface_center_wrt_world = Vector3.Scale(Block.transform.rotation * center_vertice, Block.transform.localScale) + Block.transform.position;
    }

    private float FindNearest(float[] arr, float val)
    {
        float currentNearest = arr[0];
        float currentDifference = Mathf.Abs(currentNearest - val);

        for (int i = 1; i < arr.Length; i++)
        {
            float diff = Mathf.Abs(arr[i] - val);
            if (diff < currentDifference)
            {
                currentDifference = diff;
                currentNearest = arr[i];
            }
        }
        return currentNearest;
    }

    public Vector3 GetRandomSpawnPosRelativeGroundGroup(GameObject obj, Vector2 xBounds, Vector2 zBounds)
    {
        // Spawn the object at a position on the ground that is not the goal and not near the psm
        Vector3 randomSpawnPos = Vector3.zero;
        var randomPosX = Random.Range(xBounds.x, xBounds.y);
        var randomPosZ = Random.Range(zBounds.x, zBounds.y);

        // Make the spawn relative to the ground
        // Spawn the block so that it spawns directly on the ground based on its height
        float spawnHeight = obj.transform.localScale.y / 2f;
        randomSpawnPos = SpawnGround.transform.localPosition + new Vector3(randomPosX, spawnHeight, randomPosZ);

        // Debug furthest    
        // randomSpawnPos = SpawnGround.transform.localPosition + new Vector3(xBounds.x, spawnHeight, zBounds.x);
        
        // With local position, assumes it is not in collision.
        // !!!! Make sure not in collision with tool or goal !!!
        return randomSpawnPos;
    }

    public void HitAGoal()
    {
        AddReward(-1.0f);
        m_totalPenalties -= 1.0f;
        updateBaseRewardVariable();
        EndEpisode();
    }

    public void AddBoundaryPenalty()
    {
        AddReward(-0.5f);
        m_totalPenalties -= 0.5f;
    }

    private Vector3 getUpAxis(Matrix4x4 m, int index)
    {
        Vector3 up_axis;
        if(index == 0)
        {
            up_axis = new Vector3(m[0, 1], m[1, 1], m[2, 1]); // y axis
        }
        else if(index == 1)
        {
            up_axis = new Vector3(m[0, 2], m[1, 2], m[2, 2]); // z axis
        }
        else if(index == 2)
        {
            up_axis = new Vector3(m[0, 1], m[1, 1], m[2, 1]); // -y axis
            up_axis = -up_axis;
        }
        else
        {
            up_axis = new Vector3(m[0, 2], m[1, 2], m[2, 2]); // -z axis
            up_axis = -up_axis;
        }
        return up_axis;
    }

    private int findUpBlockAxisIndex()
    {
        int curr_min = -1;
        float min_angle = 500; // Large above 180, max is 180
        Matrix4x4 m = Matrix4x4.Rotate(Block.transform.localRotation);
        for (int i = 0; i < 4; i++)
        {
            Vector3 up_axis = getUpAxis(m, i);
            float angle = Vector3.Angle(Vector3.up, up_axis);
            if(angle < min_angle)
            {
                min_angle = angle;
                curr_min = i;
            }
        }
        return curr_min;
    }

    private void updateBaseRewardVariable()
    {
        reward = m_totalPenalties + totalDenseReward;
    }


    protected override void Update()
    {
        if (Input.GetKeyDown(KeyCode.Space))
        {
            if(IsExperiment)
            {
                Debug.Log("Num Rolls: " + countRoll);
                rollBlockExperiment.numRollResults.Add(countRoll);
                rollBlockExperiment.numTriesPerGridCount += 1;
                if(rollBlockExperiment.numTriesPerGridCount == rollBlockExperiment.setNumTriesPerGrid)
                {
                    rollBlockExperiment.currentGridIdx += 1;
                    rollBlockExperiment.numTriesPerGridCount = 0;
                }

                if(rollBlockExperiment.currentGridIdx >= rollBlockExperiment.blockGridLocations.Count)
                {
                    // count
                    int oneRolls = 0;
                    int twoRolls = 0;
                    int threeRolls = 0;
                    int fourRolls = 0;
                    foreach (int numRollResult in rollBlockExperiment.numRollResults)
                    {
                        if(numRollResult >= 1)
                            oneRolls += 1;
                        if(numRollResult >= 2)
                            twoRolls += 1;
                        if(numRollResult >= 3)
                            threeRolls +=1;
                        if(numRollResult >= 4)
                            fourRolls +=1;
                    }
                    int total = rollBlockExperiment.numRollResults.Count;
                    Debug.Log("Experiment Finished Results: One, two, three, four");
                    Debug.Log(
                        oneRolls + " (" + oneRolls/total + "),"
                        + twoRolls + " (" + twoRolls/total + "),"
                        + threeRolls + " (" + threeRolls/total + "),"
                        + fourRolls + " (" + fourRolls/total + ")");
                }
            }
            EpisodeReset();
        }
    }

    public override void UpdateReward()
    {
        // Find Correct block height, needs to be here, because moving tip takes time after initialization
        // Debug.Log("block " + (Block.transform.position.y + Block.transform.localScale.y/2));
        // Debug.Log(ToolTip.transform.position.y);
    
        float current_reward = 0.0f;

        Matrix4x4 m = Matrix4x4.Rotate(Block.transform.localRotation);
        Vector3 block_up_axis = getUpAxis(m, blockAxisIndex);
        float abs_rotate_angle = Vector3.Angle(Vector3.up, block_up_axis);

        float rotate_angle = abs_rotate_angle;
        Vector3 rotate_x = Vector3.Cross(block_up_axis, Vector3.up); // left hand cross: https://docs.unity3d.com/ScriptReference/Vector3.Cross.html 
        if(Vector3.Angle(rotate_x, new Vector3(m[0, 0], m[1, 0], m[2, 0])) > 90) // rotate other direction
        {
            rotate_angle = -rotate_angle;
        }
        // Debug.Log(rotate_angle);

        float z_center_surf_to_tool_projected_on_z_dir_norm = 0.0f;
        if (useDenseRewards)
        {
            // I. Life Penalty
            float lifetime_penalty = -(float)StepCount / (float)MaxStep * LifetimePenaltyScale;
            current_reward = current_reward + lifetime_penalty;

            // II. Left of cube reward
            Vector3 z_normal_wrt_world = new Vector3(0, 0, 0);
            Vector3 z_center_wrt_world = new Vector3(0, 0, 0);;
            getNormalandCenter(
                ref z_normal_wrt_world,
                ref z_center_wrt_world,
                zNormalTriangleIdx,
                zNormalCornerVertices);
            Vector3 z_center_to_tool_tip = ToolTip.transform.position-z_center_wrt_world;
            float tool_to_z_normal_angle = Vector3.Angle(z_normal_wrt_world, z_center_to_tool_tip);
            z_center_surf_to_tool_projected_on_z_dir_norm = z_center_to_tool_tip.magnitude * Mathf.Cos(Mathf.Deg2Rad * tool_to_z_normal_angle);
            float left_of_cube_reward = 0.0f;
            if(tool_to_z_normal_angle < 90 + degTolLeftOfCube) // Is there prob with discrete reward?
            {
                left_of_cube_reward = LeftOfCubeRewardScale;
                isToolLeftofBlock = true;
            }
            else
            {
                isToolLeftofBlock = false;
            }
            current_reward = current_reward + left_of_cube_reward;

            // III. Distance reward
            //a. y height
            // float distance_tip_block_y = Mathf.Abs(
            //     ToolTip.transform.position.y - (Block.transform.position.y + Block.transform.localScale.y/2)); // Use top surface y
            // // Reward shaping
            // float distance_reward_y = Mathf.Exp(-DistanceYRewardShaping * distance_tip_block_y);
            // distance_reward_y = distance_reward_y * DistanceRewardYScale;
            // current_reward = current_reward + distance_reward_y;

            // //b. xz dist clamped circle
            // float dist_x = ToolTip.transform.position.x - Block.transform.position.x;
            // float dist_z = ToolTip.transform.position.z - Block.transform.position.z;
            // float distance_tip_block_xz = Mathf.Sqrt(dist_x * dist_x + dist_z * dist_z);
            // distance_tip_block_xz = distance_tip_block_xz - blockSizeCutoffDistance; // Block cuttoff circle for max reward
            // // Reward shaping
            // float distance_reward_xz = Mathf.Exp(-DistanceXZRewardShaping * distance_tip_block_xz);
            // distance_reward_xz = Mathf.Clamp(distance_reward_xz, -100000f, 1f);
            // distance_reward_xz = distance_reward_xz * DistanceRewardXZScale;
            // current_reward = current_reward + distance_reward_xz;

            //c. Instead just use simple clamped center distance
            float tool_block_dist = Vector3.Distance(ToolTip.transform.position, Block.transform.position);
            tool_block_dist = tool_block_dist - blockSizeCutoffDistance; // Block cuttoff circle for max reward

            float tool_block_dist_reward = Mathf.Exp(-DistanceRewardShaping * tool_block_dist);
            tool_block_dist_reward = Mathf.Clamp(tool_block_dist_reward, -100000f, 1f);
            tool_block_dist_reward = tool_block_dist_reward * DistanceRewardScale;
            current_reward = current_reward + tool_block_dist_reward;

            // (Tested) Using z_center_wrt_world as distance seems iffy when visually checked in Unity. Not at center in x axis block.

            // IV. Rotation reward
            float rolling_reward = 0.0f;
            if(MaxRollsForReward == -1 || countRoll < MaxRollsForReward)
            {
                if(rotate_angle > 0)
                {
                    rolling_reward = rotate_angle / 90f * PerRollRewardScale;
                }
            }
            current_reward = current_reward + rolling_reward;

            // Debugging
            if(LogRewardsDebug)
            {
                Debug.Log("----");
                Debug.Log("lifetime_penalty " + lifetime_penalty);
                Debug.Log("left_of_cube_reward " + left_of_cube_reward);
                // Debug.Log("distance_reward_y " + distance_reward_y);
                // Debug.Log("distance_reward_xz " + distance_reward_xz);
                Debug.Log("tool_block_dist_reward " + tool_block_dist_reward);
                Debug.Log("rolling_reward " + rolling_reward);
                // Debug.Log("full dense reward " + current_reward);
            }
        }
        else
        {
            base.UpdateReward();
        }

        // V. Sparse roll reward
        if(abs_rotate_angle > 75f)
        {
            if(rotate_angle > 75f) // Only positive direction counts as roll
            {
                countRoll++;
            }
            // Debug.Log("Count roll " + countRoll);
            findNormalandCenterOfZFacingSurface(
                ref zNormalTriangleIdx,
                ref zNormalCornerVertices);
            blockAxisIndex = findUpBlockAxisIndex();
        }
        float sparse_roll_reward = 0.0f;
        if(MaxRollsForReward == -1 || countRoll <= MaxRollsForReward)
            sparse_roll_reward = countRoll * PerRollRewardScale;
        else
            sparse_roll_reward = MaxRollsForReward * PerRollRewardScale;
        current_reward = current_reward + sparse_roll_reward;

        // VI. Update total reward
        AddReward(current_reward - totalDenseReward);
        totalDenseReward = current_reward;

        // Debugging
        if(LogRewardsDebug)
        {
            Debug.Log("sparse_roll_reward " + sparse_roll_reward);
            Debug.Log("total reward " + current_reward);
        }

        if(EndEpisodeOnMaxRolls && (countRoll == MaxRollsForReward))
        {
            maxRollsFinished = true;
            if(!EndEpisodeOnToolMovingBack)
            {
                updateBaseRewardVariable();
                EndEpisode();
            }
        }
        // Debug.Log("z_center_surf_to_tool_projected_on_z_dir_norm " + z_center_surf_to_tool_projected_on_z_dir_norm);
        if(EndEpisodeOnToolMovingBack && maxRollsFinished)
        {
            if(z_center_surf_to_tool_projected_on_z_dir_norm > 0.15f)
            {
                AddReward(1.0f);
                totalDenseReward += 1.0f;
                updateBaseRewardVariable();
                EndEpisode();
            }
        }
        updateBaseRewardVariable();
    }

    public override void Heuristic(in ActionBuffers actionsOut)
    {
        AddInputToActionBuffers(actionsOut, -Input.GetAxis("Horizontal"), "position_x");
        AddInputToActionBuffers(actionsOut, Input.GetAxis("UpDown"), "position_y");
        AddInputToActionBuffers(actionsOut, -Input.GetAxis("Vertical"), "position_z");
    }
}
