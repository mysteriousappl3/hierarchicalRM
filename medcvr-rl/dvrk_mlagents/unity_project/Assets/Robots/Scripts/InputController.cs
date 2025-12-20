using UnityEngine;

public class InputController : MonoBehaviour
{
    public RobotController robotController;

    public bool EnableGUI = true;

    public enum ActionSpace
    {
        JointSpace,
        CartesianSpace
    }
    private string[] actionSpaceStrings = new string[] {
        "Joint Space", "Cartesian Space"};
    public ActionSpace actionSpace = ActionSpace.JointSpace;


    public float speed = 20f; // degree/s

    private int currentDirectionCommand = 0;
    private readonly object DirectionCommandLock = new object();

    private int selectedJointIndex = 0;
    private string selectedJointString = "";

    private Vector2 XPositionLimit;
    private Vector2 YPositionLimit;
    private Vector2 ZPositionLimit;
    private Vector2 XRotationLimit;
    private Vector2 YRotationLimit;
    private Vector2 ZRotationLimit;

    private Vector3 currentCartesianPosition;
    private Vector3 currentCartesianRotation;

    private bool cartesianResetRequired = false;

    public void Start()
    {
        selectedJointIndex = 0;
        SetSelectedJointIndex(0);
        Reset();

        XPositionLimit = new Vector2(
            currentCartesianPosition.x + robotController.XPositionLimit.x,
            currentCartesianPosition.x + robotController.XPositionLimit.y);
        YPositionLimit = new Vector2(
            currentCartesianPosition.y + robotController.YPositionLimit.x,
            currentCartesianPosition.y + robotController.YPositionLimit.y);
        ZPositionLimit = new Vector2(
            currentCartesianPosition.z + robotController.ZPositionLimit.x,
            currentCartesianPosition.z + robotController.ZPositionLimit.y);
        
        XRotationLimit = new Vector2(
            currentCartesianRotation.x + robotController.XRotationLimit.x,
            currentCartesianRotation.x + robotController.XRotationLimit.y);
        YRotationLimit = new Vector2(
            currentCartesianRotation.y + robotController.YRotationLimit.x,
            currentCartesianRotation.y + robotController.YRotationLimit.y);
        ZRotationLimit = new Vector2(
            currentCartesianRotation.z + robotController.ZRotationLimit.x,
            currentCartesianRotation.z + robotController.ZRotationLimit.y);
    }
    
    private void SetSelectedJointIndex(int index)
    {
        if (robotController.GetActiveJointNames().Length < 1) return;
        
        if (index > robotController.GetActiveJointNames().Length - 1)
        {
            index = robotController.GetActiveJointNames().Length - 1;
        }
        else if (index < 0)
        {
            index = 0;
        }

        selectedJointString = robotController.GetActiveJointNames()[index];
        selectedJointIndex = index;
    }

    public void Reset()
    {
        robotController.ResetTip();
        UpdateReferencePose();
    }

    public void UpdateReferencePose()
    {
        Pose tipPose = robotController.GetCurrentTipPosewrtWorld();
        currentCartesianPosition = tipPose.position;
        currentCartesianRotation = robotController.GetReferenceRotation();
    }

    void Update()
    {
        if (actionSpace == ActionSpace.CartesianSpace) return;
        if (Input.GetKeyDown("right"))
        {
            SetSelectedJointIndex(selectedJointIndex + 1);
        }
        else if (Input.GetKeyDown("left"))
        {
            SetSelectedJointIndex(selectedJointIndex - 1);
        }

        // float moveDirection = Input.GetAxis("Vertical");
        if (Input.GetKey("up"))
        {
            currentDirectionCommand = 1;
        }
        else if (Input.GetKey("down"))
        {
            currentDirectionCommand = -1;
        }
        else
        {
            currentDirectionCommand = 0;
        }
    }

    public void FixedUpdate()
    {
        lock (DirectionCommandLock)
        {
            if (currentDirectionCommand == 0) return;

            float newJointCommand = robotController.GetJointCommand(
                selectedJointString);
            
            ArticulationJointType jointType = robotController.GetJointType(
                selectedJointString);

            if (jointType == ArticulationJointType.PrismaticJoint)
            {
                newJointCommand = newJointCommand + 
                    (currentDirectionCommand * Time.fixedDeltaTime * speed / 10f);
            }
            else if (jointType == ArticulationJointType.RevoluteJoint)
            {
                newJointCommand = newJointCommand + 
                    (currentDirectionCommand * Time.fixedDeltaTime * speed * Mathf.Deg2Rad);
            }

            robotController.UpdateJointCommand(
                selectedJointString, newJointCommand);
        }
    }

    public void OnGUI()
    {
        if (!EnableGUI) return;

        GUIStyle leftAlign = GUI.skin.GetStyle("Label");
        leftAlign.alignment = TextAnchor.MiddleLeft;
        // Make a background box
        
        int box_height = 700;
        if (robotController.RobotType == RobotController.Robot.Franka)
        {
            box_height = 900;
        }

        GUI.Box(new Rect(10, 10, 270, box_height), "Input Controller");

        actionSpace = (ActionSpace)GUI.Toolbar(
            new Rect(10, 40, 250, 50), (int)actionSpace, actionSpaceStrings);

        if (actionSpace == ActionSpace.JointSpace)
        {
            GUI.Label(new Rect(12, 100, 200, 20), "Joint Space Control");
            GUI.Label(new Rect(20, 130, 200, 50), "Use left/right keys to select a robot joint. Use up/down keys to move the joint.", leftAlign);
            GUI.Label(new Rect(20, 180, 240, 20), "Current Selected Joint: " + selectedJointString, leftAlign);
        
            float y = 200;
            foreach (string jointName in robotController.GetActiveJointNames())
            {
                GUI.Label(new Rect(20, y, 200, 20), jointName + ": ", leftAlign);
                y += 30;
                float jointCommand = robotController.GetJointCommand(jointName);
                Vector2 jointLimit = robotController.GetJointLimit(jointName);
                float newJointCommand = GUI.HorizontalSlider(
                    new Rect(20, y, 150, 20),
                    jointCommand,
                    jointLimit.x,
                    jointLimit.y);

                if (newJointCommand != jointCommand)
                {
                    robotController.UpdateJointCommand(jointName, newJointCommand);
                }
                GUI.Label(new Rect(180, y - 5, 200, 20), newJointCommand.ToString("F2"), leftAlign);
                y += 30;
            }

            // Reset button
            if (GUI.Button(new Rect(20, y, 150, 20), "Reset Tip"))
            {
                Reset();
            }

            cartesianResetRequired = true;
        }
        else
        {
            if (cartesianResetRequired)
            {
                Reset();
                cartesianResetRequired = false;
            }

            GUI.Label(new Rect(12, 100, 200, 20), "Cartesian Space Control");
            // Create sliders for all cartesian space values
            GUI.Label(new Rect(20, 130, 200, 20), "X: ", leftAlign);
            float newX = GUI.HorizontalSlider(
                new Rect(60, 135, 150, 20), currentCartesianPosition.x, XPositionLimit.x, XPositionLimit.y);
            GUI.Label(new Rect(20, 160, 200, 20), "Y: ", leftAlign);
            float newY = GUI.HorizontalSlider(
                new Rect(60, 165, 150, 20), currentCartesianPosition.y, YPositionLimit.x, YPositionLimit.y);
            GUI.Label(new Rect(20, 190, 200, 20), "Z: ", leftAlign);
            float newZ = GUI.HorizontalSlider(
                new Rect(60, 195, 150, 20), currentCartesianPosition.z, ZPositionLimit.x, ZPositionLimit.y);
            GUI.Label(new Rect(20, 220, 200, 20), "RX: ", leftAlign);
            float newRX = GUI.HorizontalSlider(
                new Rect(60, 225, 150, 20), currentCartesianRotation.x, XRotationLimit.x, XRotationLimit.y);
            GUI.Label(new Rect(20, 250, 200, 20), "RY: ", leftAlign);
            float newRY = GUI.HorizontalSlider(
                new Rect(60, 255, 150, 20), currentCartesianRotation.y, YRotationLimit.x, YRotationLimit.y);
            GUI.Label(new Rect(20, 280, 200, 20), "RZ: ", leftAlign);
            float newRZ = GUI.HorizontalSlider(
                new Rect(60, 285, 150, 20), currentCartesianRotation.z, ZRotationLimit.x, ZRotationLimit.y);
            
            Vector3 positionDelta = new Vector3(
                newX - currentCartesianPosition.x,
                newY - currentCartesianPosition.y,
                newZ - currentCartesianPosition.z);

            Vector3 rotationDelta = new Vector3(
                newRX - currentCartesianRotation.x,
                newRY - currentCartesianRotation.y,
                newRZ - currentCartesianRotation.z);
            
            robotController.MoveTip(positionDelta, rotationDelta, -1f);
            UpdateReferencePose();

            GUI.Label(new Rect(220, 130, 200, 20), newX.ToString("F2"), leftAlign);
            GUI.Label(new Rect(220, 160, 200, 20), newY.ToString("F2"), leftAlign);
            GUI.Label(new Rect(220, 190, 200, 20), newZ.ToString("F2"), leftAlign);
            GUI.Label(new Rect(220, 220, 200, 20), newRX.ToString("F2"), leftAlign);
            GUI.Label(new Rect(220, 250, 200, 20), newRY.ToString("F2"), leftAlign);
            GUI.Label(new Rect(220, 280, 200, 20), newRZ.ToString("F2"), leftAlign);

            // Reset button
            if (GUI.Button(new Rect(20, 310, 150, 20), "Reset Tip"))
            {
                Reset();
            }
        }
    }
}
