using UnityEngine;
using Unity.MLAgents;
using Unity.MLAgents.Actuators;
using Unity.MLAgents.Policies;
using System.Collections.Generic;
using System.Linq;
using UnityEditor;

public class BaseAgent : Agent
{
    [Header("Environment References")]
    // Environment References for base scene objects
    public GameObject ParentScene;
    public GameObject ToolTip;
    public GameObject Ground;
    public GameObject SpawnGround;
    public Light SceneLight;
    public GameObject SceneCamera;

    public enum ActionMode
    {
        Disabled,
        Discrete,
        Continuous
    }

    public struct ActionBufferInfo
    {
        public ActionMode mode;
        public int index;

        public ActionBufferInfo(ActionMode mode, int index)
        { 
            this.mode = mode;
            this.index = index;
        }
    }

    [System.Serializable]
    public struct ActionSetting
    {
        public string id;
        public ActionMode mode;

        public ActionSetting(string id, ActionMode mode)
        {
            this.id = id;
            this.mode = mode;
        }
    }

    [System.Serializable]
    public class ArmConfig : ISerializationCallbackReceiver
    {
        public GameObject RootObject;
        public string prefix;
        public ActionSetting[] ActionSettings;
        public float PositionSpeedMultiplier = 0.01f;
        [HideInInspector]
        public RobotController controller;

        [HideInInspector]
        public bool jawOpen = false;
        [SerializeField, HideInInspector]
        private bool _serielized = false;

        public void OnBeforeSerialize()
        {
            if (_serielized) return;
            ActionSettings = new ActionSetting[]
            {
                new ActionSetting("position_x", ActionMode.Continuous),
                new ActionSetting("position_y", ActionMode.Continuous),
                new ActionSetting("position_z", ActionMode.Continuous),
                new ActionSetting("jaw", ActionMode.Continuous),
                new ActionSetting("rotation_x", ActionMode.Disabled),
                new ActionSetting("rotation_y", ActionMode.Disabled),
                new ActionSetting("rotation_z", ActionMode.Disabled),
            };
            PositionSpeedMultiplier = 0.01f;
            _serielized = true;
        }

        public void OnAfterDeserialize() {}
    }

    public List<ArmConfig> Arms;

    [Header("Observation Settings")]
    public bool UseVectorObservation;

    // Private references
    protected EnvironmentParameters resetParams;
    protected Bounds areaBounds;
    protected float reward = 0f;
    protected float[][] discreteActionsBins;
    protected Dictionary<string, ActionBufferInfo> actionIndices;
    protected int continuous_i = 0;
    protected int discrete_i = 0;
    protected int uniqueEpisodeId = -1;

    public override void Initialize()
    {
        InitializeAgent();
    }

    public void InitializeAgent()
    {
        foreach (ArmConfig arm in Arms)
        {
            arm.controller = arm.RootObject.GetComponent<RobotController>();
            arm.controller.Initialize();
        }

        areaBounds = SpawnGround.GetComponent<Collider>().bounds;
        resetParams = Academy.Instance.EnvironmentParameters;

        if (DomainRandomizer.Instance == null)
        {
            Debug.LogError(@"Your Scene is missing a DomainRandomizer script, 
                            initializing a default one for you for now!");
            GameObject domObj = new GameObject("DomainRandomizer");
            DomainRandomizer rand = domObj.AddComponent<DomainRandomizer>();
        }

        var bp = GetComponent<BehaviorParameters>();
        discreteActionsBins = new float[bp.BrainParameters.ActionSpec.BranchSizes.Length][];
        for (int i = 0; i < bp.BrainParameters.ActionSpec.BranchSizes.Length; i++)
        {
            discreteActionsBins[i] = linspace(
                -1.0f,
                1.0f,
                bp.BrainParameters.ActionSpec.BranchSizes[i]);
        }

        actionIndices = new Dictionary<string, ActionBufferInfo>();

        foreach (ArmConfig arm in Arms)
        {
            if (arm.prefix != "") arm.prefix += "_";
            AddActionSettingsIntoActionMap(
                arm.ActionSettings,
                arm.prefix,
                ref actionIndices,
                ref discrete_i, ref continuous_i);
        }

        if (discreteActionsBins.Length != discrete_i ||
            bp.BrainParameters.ActionSpec.NumContinuousActions != continuous_i)
        {
            Debug.LogError("The action settings do not match the behaviour parameter settings!");
            Debug.LogError("Discrete From Brain: " + discreteActionsBins.Length + " vs Action Settings: " + discrete_i);
            Debug.LogError("Continuous From Brain: " + bp.BrainParameters.ActionSpec.NumContinuousActions + " vs Action Settings: " + continuous_i);
            throw new System.Exception("The action settings do not match the behaviour parameter settings!");
        }
    }

    public void AddActionSettingsIntoActionMap(
        ActionSetting[] actionSettings,
        string prefix,
        ref Dictionary<string, ActionBufferInfo> actionIndices,
        ref int discrete_index, ref int continuous_index)
    {
        foreach (ActionSetting setting in actionSettings)
        {
            if (setting.mode == ActionMode.Continuous)
            {
                actionIndices.Add(
                    prefix + setting.id, 
                    new ActionBufferInfo(setting.mode, continuous_index));
                continuous_index++;
            }
            else if (setting.mode == ActionMode.Discrete)
            {
                actionIndices.Add(
                    prefix  + setting.id,
                    new ActionBufferInfo(setting.mode, discrete_index));
                discrete_index++;
            }
            else
            {
                actionIndices.Add(
                    prefix + setting.id,
                    new ActionBufferInfo(setting.mode, -1));
            }
        }
    }

    protected virtual void Update()
    {
        // By default, space will open the jaw of only the first arm
        if (Input.GetKeyDown(KeyCode.Space))
        {
            Arms[0].jawOpen = !Arms[0].jawOpen;
        }
    }

    protected virtual void ResetFloor()
    {
        Color newColor = DomainRandomizer.Instance.RandomizeColor(
            SpawnGround.GetComponent<Renderer>().material.color,
            "ground_r", "ground_g", "ground_b");

        SpawnGround.GetComponent<Renderer>().material.color = newColor;
        Ground.GetComponent<Renderer>().material.color = newColor;

        var groundCollider = SpawnGround.GetComponent<Collider>();
        groundCollider.material.dynamicFriction = DomainRandomizer.Instance.RandomizeDomain(
            groundCollider.material.dynamicFriction, "dynamic_friction");
        groundCollider.material.staticFriction = DomainRandomizer.Instance.RandomizeDomain(
            groundCollider.material.staticFriction, "static_friction");
    }

    protected virtual void ResetLight()
    {
        if (SceneLight)
        {
            SceneLight.intensity = DomainRandomizer.Instance.RandomizeDomain(SceneLight.intensity, "light_intensity");
            SceneLight.transform.localPosition = DomainRandomizer.Instance.RandomizeVec3(
                SceneLight.transform.localPosition, "light_px", "light_py", "light_pz");

            if (DomainRandomizer.Instance.RandomizeDomain(
                0, "shadow_probability") < 0.5) SceneLight.shadows = LightShadows.None;
            else SceneLight.shadows = LightShadows.Soft;
        }
    }

    protected virtual void ResetCamera()
    {
        if (SceneCamera)
        {
            SceneCamera.transform.localPosition = DomainRandomizer.Instance.RandomizeVec3(
                SceneCamera.transform.localPosition, "camera_px", "camera_py", "camera_pz");

            
            Vector3 rot = DomainRandomizer.Instance.RandomizeVec3(
                SceneCamera.transform.localEulerAngles, "camera_rx", "camera_ry", "camera_rz");

            Quaternion q = Quaternion.AngleAxis(rot.y, Vector3.up) * 
                            Quaternion.AngleAxis(rot.x, Vector3.right) *
                            Quaternion.AngleAxis(rot.z, Vector3.forward);

            SceneCamera.transform.localRotation = q;

            Camera cam = SceneCamera.GetComponent<Camera>();
            cam.fieldOfView = DomainRandomizer.Instance.RandomizeDomain(
                cam.fieldOfView, "camera_fov");
        }
    }

    protected virtual void ResetTool(int armIndex, Vector3 startPosition, Vector3 startRotation)
    {
        float randX = DomainRandomizer.Instance.RandomizeDomain(
            0.0f, "tool_position_noise_x");
        float randY = DomainRandomizer.Instance.RandomizeDomain(
            0.0f, "tool_position_noise_y");
        float randZ = DomainRandomizer.Instance.RandomizeDomain(
            0.0f, "tool_position_noise_z");

        Vector3 startPos = 
            ParentScene.transform.position + startPosition + new Vector3(
                randX, randY, randZ);

        ResetArm(armIndex, startPos, startRotation);
        Arms[armIndex].controller.SetMinJawAngleRadians(0.0f);
        Arms[armIndex].jawOpen = false;
    }

    protected virtual void ResetToolColor()
    {
        RobotController psmController = GetComponent<RobotController>();
        if (psmController == null) return;
        
        // Check tool type and set the color accordingly
        Renderer[] toolRenderers = GetComponentsInChildren<Renderer>();

        if (psmController.Tool == RobotController.ToolAttachment.LargeNeedleDriver)
        {
            float toolGripperColor = DomainRandomizer.Instance.RandomizeDomain(
                toolRenderers[8].material.color.r, "tool_gripper_r");
            Color color = new Color(toolGripperColor, toolGripperColor, toolGripperColor);
            for (int i = 8; i < toolRenderers.Length; i++)
            {
                toolRenderers[i].material.color = color;
            }

            float toolShaftLinkColor = DomainRandomizer.Instance.RandomizeDomain(
                toolRenderers[7].material.color.r, "tool_shaft_r");
            color = new Color(toolShaftLinkColor, toolShaftLinkColor, toolShaftLinkColor);
            toolRenderers[7].material.color = color;
        }
        else if (psmController.Tool == RobotController.ToolAttachment.RoundTipScissor)
        {
            float toolGripperColor = DomainRandomizer.Instance.RandomizeDomain(
                toolRenderers[10].material.color.r, "tool_gripper_r");
            Color color = new Color(toolGripperColor, toolGripperColor, toolGripperColor);
            for (int i = 10; i < toolRenderers.Length; i++)
            {
                toolRenderers[i].material.color = color;
            }

            float toolRollLinkColor = DomainRandomizer.Instance.RandomizeDomain(
                toolRenderers[8].material.color.r, "tool_roll_r");
            color = new Color(toolRollLinkColor, toolRollLinkColor, toolRollLinkColor);
            for (int i = 8; i < 10; i++)
            {
                toolRenderers[i].material.color = color;
            }

            float toolShaftLinkColor = DomainRandomizer.Instance.RandomizeDomain(
                toolRenderers[7].material.color.r, "tool_shaft_r");
            color = new Color(toolShaftLinkColor, toolShaftLinkColor, toolShaftLinkColor);
            toolRenderers[7].material.color = color;
        }
    }

    public virtual void EpisodeReset()
    {
        ResetFloor();
        ResetLight();
        ResetCamera();
    }

    public bool CheckColliders(Vector3 position)
    {
        return Physics.CheckBox(position, new Vector3(0.5f, 0.01f, 0.5f));
    }

    public virtual Vector3 GetRandomSpawnPos(GameObject obj, Vector2 xBounds, Vector2 zBounds, System.Func<Vector3, bool> checkSpawnCondition = null, int spawnTries = 50)
    {
        // Spawn the object at a position on the ground that is not the goal and not near the psm
        bool foundNewSpawnLocation = false;
        Vector3 randomSpawnPos = Vector3.zero;

        for (int i = 0; i < spawnTries; i++)
        {
            var randomPosX = Random.Range(xBounds.x, xBounds.y);
            var randomPosZ = Random.Range(zBounds.x, zBounds.y);

            float spawnHeight = obj.transform.localScale.y / 2f;
            randomSpawnPos = SpawnGround.transform.position + new Vector3(randomPosX, spawnHeight, randomPosZ);

            // When no function is provided just return the random position
            if (checkSpawnCondition == null)
            {
                foundNewSpawnLocation = true;
                break;
            }

            // Check if the spawn location is valid using the checkSpawnCondition function
            if (checkSpawnCondition(randomSpawnPos) == true)
            {
                foundNewSpawnLocation = true;
                break;
            }
        }

        if (!foundNewSpawnLocation) throw new System.Exception("Spawn tried more than 50 times, Janky");
        return randomSpawnPos;
    }

    public override void OnEpisodeBegin()
    {
        EpisodeRecorder.Instance?.RecordEndEpisode(uniqueEpisodeId, reward, ParentScene);
        uniqueEpisodeId = EpisodeRecorder.Instance ? EpisodeRecorder.Instance.StartNewEpisode(uniqueEpisodeId, ParentScene) : -1;
        EpisodeReset();
        reward = 0;
    }

    public void ResetArm(int armIndex)
    {
        Arms[armIndex].controller.ResetTip();
    }

    public void ResetArm(int armIndex, Vector3 tipPositionwrtWorld)
    {
        Arms[armIndex].controller.ResetTip(tipPositionwrtWorld, Arms[armIndex].controller.GetStartTipRotation());
    }

    public void ResetArm(int armIndex, Vector3 tipPositionwrtWorld, Vector3 tipRotationwrtWorld)
    {
        Arms[armIndex].controller.ResetTip(tipPositionwrtWorld, Quaternion.Euler(tipRotationwrtWorld));
    }

    public void TaskComplete(float reward)
    {
        AddReward(reward);
        this.reward += reward;
        EndEpisode();
    }

    public void TaskFailure(float reward)
    {
        AddReward(reward);
        this.reward += reward;
        EndEpisode();
    }

    public void AddPenalty(float reward)
    {
        AddReward(reward);
        this.reward += reward;
    }

    public virtual void GoalTriggerCallback() { }

    public virtual void PenaltyTriggerCallback() { }

    public virtual void UpdateReward()
    {
        // Negative step reward to encourage fast task solving
        AddReward(-1f / MaxStep);
        reward += (-1f / MaxStep);
    }

    public virtual void CheckEndConditions() { }

    private float RetrieveActionFromBuffer(
        ActionBuffers actionBuffers,
        ActionMode mode,
        int bufferIndex)
    {
        float action = 0f;
        switch (mode)
        {
            case ActionMode.Disabled:
                break;
            case ActionMode.Discrete:
                action = discreteActionsBins[bufferIndex][actionBuffers.DiscreteActions[bufferIndex]];
                break;
            case ActionMode.Continuous:
                action = actionBuffers.ContinuousActions[bufferIndex];
                break;
            default:
                break;
        }
        return action;
    }

    private RobotSignal GetCartesianSignalFromActionBuffer(
        ActionBuffers actionBuffers, string toolPrefix = "")
    {
        RobotSignal robotSignal = new RobotSignal();

        robotSignal.PositionSignal = new Vector3(
            RetrieveActionFromBuffer(
                actionBuffers,
                actionIndices[toolPrefix + "position_x"].mode,
                actionIndices[toolPrefix + "position_x"].index),
            RetrieveActionFromBuffer(
                actionBuffers,
                actionIndices[toolPrefix + "position_y"].mode,
                actionIndices[toolPrefix + "position_y"].index),
            RetrieveActionFromBuffer(
                actionBuffers,
                actionIndices[toolPrefix + "position_z"].mode,
                actionIndices[toolPrefix + "position_z"].index));

        if (actionIndices[toolPrefix + "jaw"].mode == ActionMode.Disabled) 
            robotSignal.JawSignal = -1;
        else
        {
            robotSignal.JawSignal = RetrieveActionFromBuffer(
                actionBuffers,
                actionIndices[toolPrefix + "jaw"].mode,
                actionIndices[toolPrefix + "jaw"].index);
        }

        robotSignal.RotationSignal = new Vector3(
            RetrieveActionFromBuffer(
                actionBuffers,
                actionIndices[toolPrefix + "rotation_x"].mode,
                actionIndices[toolPrefix + "rotation_x"].index),
            RetrieveActionFromBuffer(
                actionBuffers,
                actionIndices[toolPrefix + "rotation_y"].mode,
                actionIndices[toolPrefix + "rotation_y"].index),
            RetrieveActionFromBuffer(
                actionBuffers,
                actionIndices[toolPrefix + "rotation_z"].mode,
                actionIndices[toolPrefix + "rotation_z"].index));
        return robotSignal;
    }

    private (int, List<float>) RetrievePrimitiveParams(
        ActionBuffers actionBuffers, string toolPrefix = "")
    {
        int primitiveIndex = (int)actionBuffers.DiscreteActions[
            actionIndices[toolPrefix + "primitive"].index];

        List<float> primitiveParams = new List<float>
        {
            RetrieveActionFromBuffer(
                actionBuffers,
                actionIndices[toolPrefix + "theta"].mode,
                actionIndices[toolPrefix + "theta"].index),
            RetrieveActionFromBuffer(
                actionBuffers,
                actionIndices[toolPrefix + "distance"].mode,
                actionIndices[toolPrefix + "distance"].index)
        };

        return (primitiveIndex, primitiveParams);
    }

    public override void OnActionReceived(ActionBuffers actionBuffers)
    {
        if (StepCount == 0) return;

        foreach (ArmConfig arm in Arms)
        {
            RobotSignal robotSignal = new RobotSignal();

            if (arm.controller.Controller == RobotController.ControllerType.Cartesian)
            {
                robotSignal = GetCartesianSignalFromActionBuffer(
                    actionBuffers, arm.prefix);
            }
            else if (arm.controller.Controller == RobotController.ControllerType.Primitive)
            {
                (int primitiveIndex, List<float> primitiveParams) = RetrievePrimitiveParams(
                    actionBuffers, arm.prefix);
                robotSignal = arm.controller.GetCartesianSignalFromPrimitive(
                    primitiveIndex, primitiveParams);
            }

            arm.controller.MoveTip(
                robotSignal.PositionSignal * arm.PositionSpeedMultiplier,
                robotSignal.RotationSignal,
                robotSignal.JawSignal);
        }

        UpdateReward();

        // TODO: Fix Logging for multi-arm
        // Records the output action without modifiers
        // EpisodeRecorderRecordStep(
        //     robotSignal.PositionSignal,
        //     robotSignal.RotationSignal,
        //     robotSignal.JawSignal);

        CheckEndConditions();
    }

    protected virtual void EpisodeRecorderRecordStep(Vector3 positionSignal, Quaternion rotationSignal, float jawSignal)
    {
        EpisodeRecorder.Instance?.RecordStep(uniqueEpisodeId, StepCount, positionSignal, rotationSignal, jawSignal, reward, SceneCamera.GetComponent<Camera>());
    }


    protected int ConvertInputToDiscreteBin(float axisInput, int binIndex, float tol = 10e-3f)
    {
        if (axisInput < -tol) return 0;
        else if (axisInput > tol) return discreteActionsBins[binIndex].Length - 1;
        else return discreteActionsBins[binIndex].Length / 2; // assumes odd bins length
    }

    protected void AddInputToActionBuffers(
        in ActionBuffers actionsOut,
        float axisInput,
        string actionName)
    {
        var continuousActionsOut = actionsOut.ContinuousActions;
        var discreteActionsOut = actionsOut.DiscreteActions;

        if (actionIndices[actionName].mode == ActionMode.Continuous)
            continuousActionsOut[actionIndices[actionName].index] = axisInput;
        else if (actionIndices[actionName].mode == ActionMode.Discrete)
            discreteActionsOut[actionIndices[actionName].index] =
                ConvertInputToDiscreteBin(axisInput, actionIndices[actionName].index);
    }

    public override void Heuristic(in ActionBuffers actionsOut)
    {
        AddInputToActionBuffers(actionsOut, Input.GetAxis("Horizontal"), "position_x");
        AddInputToActionBuffers(actionsOut, Input.GetAxis("Vertical"), "position_y");
        AddInputToActionBuffers(actionsOut, Input.GetAxis("UpDown"), "position_z");
        AddInputToActionBuffers(actionsOut, Arms[0].jawOpen ? 1f : -1f, "jaw");
    }

    public static float[] linspace(float startval, float endval, int steps)
    {
        float interval = (endval / Mathf.Abs(endval)) * Mathf.Abs(endval - startval) / (steps - 1);
        return (from val in Enumerable.Range(0, steps)
                select startval + (val * interval)).ToArray();
    }
}
