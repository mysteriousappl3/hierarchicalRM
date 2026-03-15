using UnityEngine;
using UnityEngine.UI;
using System.IO;
using System.Collections;
using System.Collections.Generic;
using System;
using System.Threading.Tasks;

public class DropDownAPI : MonoBehaviour
{
    public LowLevelMotor motor;
    public SnipCameraScript cam;
    
    /////////// API Calls Stuff
    public Main main;
    public H1ActionGenerator h1ActionGenerator;
    public H2ActionGenerator h2ActionGenerator;
    public SceneDescriptor sceneDescriptor;
    public StateDescriptor stateDescriptor;
    public DecisionBot decisionBot;
    public InnerBot innerBot;
    public OuterBot outerBot;

    public List<string> actionsExecutedSoFar = new();

    /////////////////////
    public Dropdown plannerDropDown;

    public InputField taskInputField;
    public Button startButton;

    void Start()
    {
        plannerDropDown.value = 0;
        plannerDropDown.RefreshShownValue();

        startButton.interactable = false;
        taskInputField.onValueChanged.AddListener(OnTaskInputChanged);
        startButton.onClick.AddListener(OnStartButtonClicked);
    }

    private void OnTaskInputChanged(string value)
    {
        startButton.interactable = !string.IsNullOrWhiteSpace(value);
    }

    public void OnStartButtonClicked()
    {
        main.userInstruction = taskInputField.text.Trim();
        StartCoroutine(APIRunner());
    }


    public IEnumerator testMotorFunctions()
    {

        // MoveHoop(red_peg, blue_peg)
        yield return StartCoroutine(motor.MoveCoroutine(2));
        yield return StartCoroutine(motor.GrabCoroutine());
        yield return StartCoroutine(motor.MoveCoroutine(3));
        yield return StartCoroutine(motor.DropCoroutine());
        yield return StartCoroutine(cam.SaveImage());
        main.imageCounter += 1;

        // MoveHoop(green_peg, red_peg)
        yield return StartCoroutine(motor.MoveCoroutine(1));
        yield return StartCoroutine(motor.GrabCoroutine());
        yield return StartCoroutine(motor.MoveCoroutine(2));
        yield return StartCoroutine(motor.DropCoroutine());
        yield return StartCoroutine(cam.SaveImage());
        main.imageCounter += 1;

        // MoveHoop(red_peg, blue_peg)
        yield return StartCoroutine(motor.MoveCoroutine(2));
        yield return StartCoroutine(motor.GrabCoroutine());
        yield return StartCoroutine(motor.MoveCoroutine(3));
        yield return StartCoroutine(motor.DropCoroutine());
        yield return StartCoroutine(cam.SaveImage());
        main.imageCounter += 1;

        // MoveHoop(green_peg, red_peg)
        yield return StartCoroutine(motor.MoveCoroutine(1));
        yield return StartCoroutine(motor.GrabCoroutine());
        yield return StartCoroutine(motor.MoveCoroutine(2));
        yield return StartCoroutine(motor.DropCoroutine());
        yield return StartCoroutine(cam.SaveImage());
        main.imageCounter += 1;

        // MoveHoop(blue_peg, red_peg)
        yield return StartCoroutine(motor.MoveCoroutine(3));
        yield return StartCoroutine(motor.GrabCoroutine());
        yield return StartCoroutine(motor.MoveCoroutine(2));
        yield return StartCoroutine(motor.DropCoroutine());
        yield return StartCoroutine(cam.SaveImage());
        main.imageCounter += 1;

        // MoveHoop(blue_peg, red_peg)
        yield return StartCoroutine(motor.MoveCoroutine(3));
        yield return StartCoroutine(motor.GrabCoroutine());
        yield return StartCoroutine(motor.MoveCoroutine(2));
        yield return StartCoroutine(motor.DropCoroutine());
        yield return StartCoroutine(cam.SaveImage());
        main.imageCounter += 1;

        // MoveHoop(green_peg, blue_peg)
        yield return StartCoroutine(motor.MoveCoroutine(1));
        yield return StartCoroutine(motor.GrabCoroutine());
        yield return StartCoroutine(motor.MoveCoroutine(3));
        yield return StartCoroutine(motor.DropCoroutine());
        yield return StartCoroutine(cam.SaveImage());
        main.imageCounter += 1;

        // MoveHoop(red_peg, green_peg)
        yield return StartCoroutine(motor.MoveCoroutine(2));
        yield return StartCoroutine(motor.GrabCoroutine());
        yield return StartCoroutine(motor.MoveCoroutine(1));
        yield return StartCoroutine(motor.DropCoroutine());
        yield return StartCoroutine(cam.SaveImage());
        main.imageCounter += 1;

        // MoveHoop(red_peg, green_peg)
        yield return StartCoroutine(motor.MoveCoroutine(2));
        yield return StartCoroutine(motor.GrabCoroutine());
        yield return StartCoroutine(motor.MoveCoroutine(1));
        yield return StartCoroutine(motor.DropCoroutine());
        yield return StartCoroutine(cam.SaveImage());
        main.imageCounter += 1;

        // MoveHoop(red_peg, blue_peg)
        yield return StartCoroutine(motor.MoveCoroutine(2));
        yield return StartCoroutine(motor.GrabCoroutine());
        yield return StartCoroutine(motor.MoveCoroutine(3));
        yield return StartCoroutine(motor.DropCoroutine());
        yield return StartCoroutine(cam.SaveImage());
        main.imageCounter += 1;

        // MoveHoop(green_peg, red_peg)
        yield return StartCoroutine(motor.MoveCoroutine(1));
        yield return StartCoroutine(motor.GrabCoroutine());
        yield return StartCoroutine(motor.MoveCoroutine(2));
        yield return StartCoroutine(motor.DropCoroutine());
        yield return StartCoroutine(cam.SaveImage());
        main.imageCounter += 1;

        // MoveHoop(red_peg, blue_peg)
        yield return StartCoroutine(motor.MoveCoroutine(2));
        yield return StartCoroutine(motor.GrabCoroutine());
        yield return StartCoroutine(motor.MoveCoroutine(3));
        yield return StartCoroutine(motor.DropCoroutine());
        yield return StartCoroutine(cam.SaveImage());
        main.imageCounter += 1;

        // MoveHoop(green_peg, red_peg)
        yield return StartCoroutine(motor.MoveCoroutine(1));
        yield return StartCoroutine(motor.GrabCoroutine());
        yield return StartCoroutine(motor.MoveCoroutine(2));
        yield return StartCoroutine(motor.DropCoroutine());
        yield return StartCoroutine(cam.SaveImage());
        main.imageCounter += 1;

        yield break;
    }

    private void CleanForReplan()
    {
        main.h1Toh0Mapping.Clear();
        main.h2Toh1Mapping.Clear();
        main.functionParamSignature.Clear();
        main.functionToCallsWithArgs.Clear();
        main.subtaskFunctions.Clear();
        actionsExecutedSoFar.Clear();
    }

    public IEnumerator APIRunner()
    {
        while (main.totalReplanAttempts >= 0)
        {
            CleanForReplan();

            do
            {
                // Scene Descriptor
                yield return StartCoroutine(cam.SaveImage());  // This increases the image counter locally first to save new image and we update the main.imageCounter to read this new image
                main.imageCounter += 1;
                yield return StartCoroutine(sceneDescriptor.generateSceneDescription());
                if (sceneDescriptor.output.Contains("NO"))
                {
                    Debug.Log("Scene is not valid. Attempting to REPLAN");
                    // Set the totalReplanAttempts to -1 as we want to termiante
                    main.totalReplanAttempts -= 1;
                    continue;
                }
                // //// State Descriptor
                yield return StartCoroutine(stateDescriptor.generateStateDescription());
                yield return StartCoroutine(innerBot.verifyPlan(true));
                main.totalReplanAttempts -= 1;
                Debug.Log("Total replan attempts = " + main.totalReplanAttempts);
            } while ((innerBot.verdict.Contains("NO") || sceneDescriptor.output.Contains("NO")) && main.totalReplanAttempts >= 0);
            if (main.totalReplanAttempts < 0)
            {
                break;
            }
            
            main.totalReplanAttempts += 1;
            do
            {
                CleanForReplan();

                yield return StartCoroutine(h1ActionGenerator.generateH1Actions());
                // H2 Action Generator
                yield return StartCoroutine(h2ActionGenerator.generateH2Actions());
                // Decision Bot
                yield return StartCoroutine(decisionBot.generateDecisionBotPlan());
                // Inner Bot
                yield return StartCoroutine(innerBot.verifyPlan(false));
                main.totalReplanAttempts -= 1;
            } while (innerBot.verdict.Contains("NO") && main.totalReplanAttempts >= 0);
            if (main.totalReplanAttempts < 0)
            {
                break;
            }

            Debug.Log("PLAN IS VERIFIED AND VALID!");
            innerBot.output = "";
            Debug.Log("[Robot Controller] -- Executing Functions now");

            if (string.IsNullOrEmpty(main.prevState))
            {
                main.prevState = main.initialSceneDesc;
            }

            if (main.subtaskFunctions.Count == 0)
            {
                Debug.LogWarning("No functions to execute. Skipping execution phase and proceeding to OuterBot Verification of states.");
                yield return StartCoroutine(cam.SaveImage());
                main.imageCounter += 1;

                // Before calling, call scene descriptor and check if output is NO. If yes, then break out of the while loop
                yield return StartCoroutine(sceneDescriptor.generateSceneDescription());
                if (sceneDescriptor.output.Contains("NO"))
                {
                    Debug.Log("[OUTER BOT] -- Non-Recoverable Scene Error Detected. Terminating Process.");
                    // Set the totalReplanAttempts to -1 as we want to termiante
                    main.totalReplanAttempts = -1;
                    yield break;
                }

                string finalGoalState = main.subtaskGoalstates[main.subtaskGoalstates.Count - 1];
                string finalSubtaskNL = main.subtaskDescriptions[main.subtaskDescriptions.Count - 1];

                yield return StartCoroutine(outerBot.verifyTaskCompletion(finalSubtaskNL, "Same as final goal state", finalGoalState));

                string rawVerdict = outerBot.feedback
                                        .Trim()
                                        .Replace("`", "")
                                        .Replace("\"", "")
                                        .Replace("“", "")
                                        .Replace("”", "")
                                        .Replace("’", "")
                                        .Replace("‘", "")
                                        .ToUpperInvariant();

                string[] verdictLines = rawVerdict.Split(new[] { '\n', '\r' }, StringSplitOptions.RemoveEmptyEntries);
                string verdict = verdictLines[0].Trim();

                main.prevState = sceneDescriptor.output;

                Debug.Log("Outer Bot Result = " + verdict);
                Debug.Log($"[OUTERBOT] Cleaned verdict line: '{verdict}'");

                if (verdict.Contains("SUCCESS"))
                {
                    // If we reach here, then that means the task has been executed successfully
                    Debug.Log("TASK COMPLETED SUCCESSFULLY!");
#if UNITY_EDITOR
                    UnityEditor.EditorApplication.isPlaying = false;
#endif
                    yield break;
                }

                Debug.Log("Replanning task!");
                main.totalReplanAttempts -= 1;
                // outerBot.output = "";
                // outerBot.lastResponseId = null;
                // sceneDescriptor.lastResponseId = null;
                continue;

            }

            bool replan = false;
            // Loop through seq of functions to execute per subtask
            for (int idx = 0; idx < main.subtaskFunctions.Count; idx++)
            {
                Debug.Log($"Executing Subtask -- {main.subtaskDescriptions[idx]}");
                Debug.Log($"Subtask has {main.subtaskFunctions[idx].Count} functions to execute");

                foreach (string action in main.subtaskFunctions[idx])
                {
                    Debug.Log($"Executing H1 Function : {action}");
                    yield return StartCoroutine(main.RunHighLevelFunction(action));

                    actionsExecutedSoFar.Add(action);
                }
                
                yield return StartCoroutine(cam.SaveImage());
                main.imageCounter += 1;
                yield return StartCoroutine(sceneDescriptor.generateSceneDescription());
                if (sceneDescriptor.output.Contains("NO"))
                {
                    Debug.Log("[SceneDescriptor] -- Non-Recoverable Scene Error Detected. Terminating Process.");
                    // Set the totalReplanAttempts to -1 as we want to termiante
                    main.totalReplanAttempts = -1;
                    yield break;
                }

                string finalGoalState = main.subtaskGoalstates[main.subtaskGoalstates.Count - 1];
                string subtaskGoalState;
                if (idx == main.subtaskGoalstates.Count - 1)
                {
                    subtaskGoalState = "Same as final goal state";
                }
                else
                {
                    subtaskGoalState = main.subtaskGoalstates[idx];
                }

                string subtaskNL = main.subtaskDescriptions[idx];

                yield return StartCoroutine(outerBot.verifyTaskCompletion(subtaskNL, subtaskGoalState, finalGoalState));

                string rawVerdict = outerBot.feedback
                                        .Trim()
                                        .Replace("`", "")
                                        .Replace("\"", "")
                                        .Replace("“", "")
                                        .Replace("”", "")
                                        .Replace("’", "")
                                        .Replace("‘", "")
                                        .ToUpperInvariant();

                
                string[] verdictLines = rawVerdict.Split(new[] { '\n', '\r' }, StringSplitOptions.RemoveEmptyEntries);
                string verdict = verdictLines[0].Trim();

                main.prevState = sceneDescriptor.output;

                Debug.Log("Outer Bot Result = " + verdict);
                Debug.Log($"[OUTERBOT] Raw verdict: '{rawVerdict}'");
                Debug.Log($"[OUTERBOT] Cleaned verdict line: '{verdict}'");

                if (verdict.Contains("SUBTASK SUCCESS"))
                {
                    Debug.Log("Subtask completed successfully. Onto the next subtask!");

                    continue;

                }

                if (verdict.Contains("TASK SUCCESS"))
                {
                    Debug.Log("TASK COMPLETED SUCCESSFULLY!");
#if UNITY_EDITOR
                    UnityEditor.EditorApplication.isPlaying = false;
#endif
                    yield break;
                }
                // NON-RECOVERABLE --> Error requiring human intervention. Terminate process
                else if (verdict.Contains("NON-RECOVERABLE"))
                {
                    Debug.Log("[NON-RECOVERABLE ERROR] -- Major error. Requires human intervention. Terminating process!");
                    yield break;

                }
                // RECOVERABLE ERROR --> Replanning required from our definition
                else if (verdict.Contains("RECOVERABLE"))
                {
                    Debug.Log("[RECOVERABLE ERROR] -- Replanning Task!");

                    replan = true;
                    break;
                }
            }

            if (replan)
            {
                main.totalReplanAttempts -= 1;
                continue;
            }
        }

        if (main.totalReplanAttempts < 0)
        {
            Debug.Log("MAXIMUM REPLAN ATTEMPTS EXCEDED! TERMINATING PROGRAM");
#if UNITY_EDITOR
            UnityEditor.EditorApplication.isPlaying = false;
#endif
            yield break;
        }
    }
}
