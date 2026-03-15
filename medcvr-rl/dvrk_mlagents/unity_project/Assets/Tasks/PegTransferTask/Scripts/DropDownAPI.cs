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

    void Start()
    {
        plannerDropDown.value = 0;
        plannerDropDown.RefreshShownValue();

        // Render the camera view into an image
        // yield return StartCoroutine(cam.SaveImage());
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


        // yield return StartCoroutine(cam.SaveImage());
        // main.imageCounter += 1;
        // yield return StartCoroutine(sceneDescriptor.generateSceneDescription());
        // if (main.prevState == "")
        // {
        //     main.prevState = main.initialSceneDesc;
        // }

        // yield return StartCoroutine(motor.MoveCoroutine(1));
        // yield return StartCoroutine(motor.GrabCoroutine());
        // yield return StartCoroutine(motor.MoveCoroutine(2));
        // yield return StartCoroutine(motor.DropCoroutine());

        // yield return StartCoroutine(cam.SaveImage());
        // main.imageCounter += 1;
        // yield return StartCoroutine(sceneDescriptor.generateSceneDescription());

        // yield return StartCoroutine(outerBot.verifyTaskCompletion());
        // Debug.Log("RESPOS = " + outerBot.output);
        // main.prevState = sceneDescriptor.output;
        // // Debug.Log("Prev State # 1= " + main.prevState);

        // yield return StartCoroutine(motor.MoveCoroutine(1));
        // yield return StartCoroutine(motor.GrabCoroutine());
        // yield return StartCoroutine(motor.MoveCoroutine(3));
        // yield return StartCoroutine(motor.DropCoroutine());

        // yield return StartCoroutine(cam.SaveImage());
        // main.imageCounter += 1;
        // yield return StartCoroutine(sceneDescriptor.generateSceneDescription());
        // yield return StartCoroutine(outerBot.verifyTaskCompletion());
        // Debug.Log("RESPOS = " + outerBot.output);
        // main.prevState = sceneDescriptor.output;
        // // Debug.Log("Prev State # 2= " + main.prevState);

        // yield return StartCoroutine(motor.MoveCoroutine(2));
        // yield return StartCoroutine(motor.GrabCoroutine());
        // yield return StartCoroutine(motor.MoveCoroutine(3));
        // yield return StartCoroutine(motor.DropCoroutine());

        // yield return StartCoroutine(cam.SaveImage());
        // main.imageCounter += 1;
        // yield return StartCoroutine(sceneDescriptor.generateSceneDescription());
        // yield return StartCoroutine(outerBot.verifyTaskCompletion());
        // Debug.Log("RESPOS = " + outerBot.output);
        // main.prevState = sceneDescriptor.output;
        // // Debug.Log("Prev State # 3= " + main.prevState);

        // yield return StartCoroutine(motor.MoveCoroutine(1));
        // yield return StartCoroutine(motor.GrabCoroutine());
        // yield return StartCoroutine(motor.MoveCoroutine(2));
        // yield return StartCoroutine(motor.DropCoroutine());

        // yield return StartCoroutine(cam.SaveImage());
        // main.imageCounter += 1;
        // yield return StartCoroutine(sceneDescriptor.generateSceneDescription());
        // yield return StartCoroutine(outerBot.verifyTaskCompletion());
        // Debug.Log("RESPOS = " + outerBot.output);
        // main.prevState = sceneDescriptor.output;
        // // Debug.Log("Prev State # 4= " + main.prevState);

        // yield return StartCoroutine(motor.MoveCoroutine(3));
        // yield return StartCoroutine(motor.GrabCoroutine());
        // yield return StartCoroutine(motor.MoveCoroutine(1));
        // yield return StartCoroutine(motor.DropCoroutine());

        // yield return StartCoroutine(cam.SaveImage());
        // main.imageCounter += 1;
        // yield return StartCoroutine(sceneDescriptor.generateSceneDescription());
        // yield return StartCoroutine(outerBot.verifyTaskCompletion());
        // Debug.Log("RESPOS = " + outerBot.output);
        // main.prevState = sceneDescriptor.output;
        // // Debug.Log("Prev State # 5= " + main.prevState);

        // yield return StartCoroutine(motor.MoveCoroutine(3));
        // yield return StartCoroutine(motor.GrabCoroutine());
        // yield return StartCoroutine(motor.MoveCoroutine(2));
        // yield return StartCoroutine(motor.DropCoroutine());

        // yield return StartCoroutine(cam.SaveImage());
        // main.imageCounter += 1;
        // yield return StartCoroutine(sceneDescriptor.generateSceneDescription());
        // yield return StartCoroutine(outerBot.verifyTaskCompletion());
        // Debug.Log("RESPOS = " + outerBot.output);
        // main.prevState = sceneDescriptor.output;
        // // Debug.Log("Prev State # 6= " + main.prevState);

        // yield return StartCoroutine(motor.MoveCoroutine(1));
        // yield return StartCoroutine(motor.GrabCoroutine());
        // yield return StartCoroutine(motor.MoveCoroutine(2));
        // yield return StartCoroutine(motor.DropCoroutine());

        // yield return StartCoroutine(cam.SaveImage());
        // main.imageCounter += 1;
        // yield return StartCoroutine(sceneDescriptor.generateSceneDescription());
        // yield return StartCoroutine(outerBot.verifyTaskCompletion());
        // Debug.Log("RESPOS = " + outerBot.output);

        // Debug.Log("Image #1");
        // yield return StartCoroutine(cam.SaveImage());
        // yield return StartCoroutine(motor.MoveCoroutine(1));
        // yield return StartCoroutine(motor.GrabCoroutine());
        // yield return StartCoroutine(motor.MoveCoroutine(2));
        // yield return StartCoroutine(motor.DropCoroutine());
        // Debug.Log("Image #2");
        // yield return StartCoroutine(cam.SaveImage());
        // yield return StartCoroutine(motor.MoveCoroutine(1));
        // yield return StartCoroutine(motor.GrabCoroutine());
        // yield return StartCoroutine(motor.MoveCoroutine(2));
        // yield return StartCoroutine(motor.DropCoroutine());
        // Debug.Log("Image #3");
        // yield return StartCoroutine(cam.SaveImage());
        // yield return StartCoroutine(motor.MoveCoroutine(1));
        // yield return StartCoroutine(motor.GrabCoroutine());
        // yield return StartCoroutine(motor.MoveCoroutine(3));
        // yield return StartCoroutine(motor.DropCoroutine());
        // Debug.Log("Image #4");
        // yield return StartCoroutine(cam.SaveImage());
        // yield return StartCoroutine(motor.MoveCoroutine(3));
        // yield return StartCoroutine(motor.GrabCoroutine());
        // yield return StartCoroutine(motor.MoveCoroutine(2));
        // yield return StartCoroutine(motor.DropCoroutine());

        yield break;
    }

    // Performs decision making for the planning dropdown option:
    // Actions can be: Take ScreenShot
    // Wait for python script to run
    // Execute plan
    public void DecisionMaker()
    {
        int decisionIdx = plannerDropDown.value;

        if (decisionIdx == 0)
        {
            return;
        }

        switch (decisionIdx)
        {
            case 1:
                StartCoroutine(cam.SaveImage());
                break;

            case 2:
                StartCoroutine(APIRunner());
                break;
        }
    }


    private void CleanForReplan()
    {
        // Reset previous h1 & h2 function mapping and outputs
            main.h1Toh0Mapping.Clear();
            main.h2Toh1Mapping.Clear();
            main.functionParamSignature.Clear();
            main.functionToCallsWithArgs.Clear();
            // Remove any old plan functions stored in variable
            // main.allFunctions.Clear();
            main.subtaskFunctions.Clear();
            actionsExecutedSoFar.Clear();
    }

    public IEnumerator replanVlmRunner()
    {
        main.totalReplanAttempts = 15;   // This means we only call API once so not stuck in loop for testing.
        
        while (main.totalReplanAttempts >= 0)
        {
            CleanForReplan();

            string outerBotVerdict = "";
            do
            {
                do
                {
                    yield return StartCoroutine(cam.SaveImage());  // This increases the image counter locally first to save new image and we update the main.imageCounter to read this new image
                    main.imageCounter += 1;
                    yield return StartCoroutine(decisionBot.generateDecisionBotPlan());
                    yield return StartCoroutine(innerBot.verifyPlan(true));
                } while (innerBot.verdict.Contains("NO") && main.totalReplanAttempts >= 0);
                if (main.totalReplanAttempts < 0)
                    break;

                // Extract primitive moves from decisionBot.output using regex (no flags)
                List<string> extractedFuncs = new List<string>();
                string output = decisionBot.output;
                // Regex to match primitive function calls (MoveCoroutine, GrabCoroutine, DropCoroutine)
                var matches = System.Text.RegularExpressions.Regex.Matches(output, @"(MoveCoroutine|GrabCoroutine|DropCoroutine)\s*\([^\)]*\)");
                foreach (System.Text.RegularExpressions.Match match in matches)
                {
                    string funcCall = match.Value.Trim();
                    if (!string.IsNullOrEmpty(funcCall))
                        extractedFuncs.Add(funcCall);
                }
                // Also match GrabCoroutine() and DropCoroutine() without arguments
                var noArgMatches = System.Text.RegularExpressions.Regex.Matches(output, @"(GrabCoroutine|DropCoroutine)\s*\(\s*\)");
                foreach (System.Text.RegularExpressions.Match match in noArgMatches)
                {
                    string funcCall = match.Value.Trim();
                    if (!string.IsNullOrEmpty(funcCall) && !extractedFuncs.Contains(funcCall))
                        extractedFuncs.Add(funcCall);
                }

                if (extractedFuncs.Count == 0)
                {
                    Debug.LogError("Could not find any primitive moves in DecisionBot output.");
                }

                foreach (string funcCall in extractedFuncs)
                {
                    main.ParseFunctionCall(funcCall, out string funcName, out List<string> args);
                    yield return StartCoroutine(main.CallPrimitiveAndWait(funcName, args));
                }


                yield return StartCoroutine(cam.SaveImage());
                main.imageCounter += 1;
                yield return StartCoroutine(outerBot.verifyTaskCompletionReplanVlm(decisionBot.output));
                if (outerBot.output.Contains("YES"))
                {
                    Debug.Log("TASK COMPLETED SUCCESSFULLY!");
#if UNITY_EDITOR
                    UnityEditor.EditorApplication.isPlaying = false;
#endif
                    yield break;
                }
            } while (outerBotVerdict.Contains("NO") && main.totalReplanAttempts >= 0);

        }
    }

    public IEnumerator APIRunner()
    {
        // // Test running main method for H1 action
        // Debug.Log("BREAKING DOWN H1 ACTION : MoveHoop()");
        // main.RunHighLevelFunction("MoveHoop(green, red)");
        // // Test with H2 hierarchy function



        //// Action State Transition
        //// yield return StartCoroutine(actionStateTransition.generateTransitionFunctions());
        //// Decision Bot
        //yield return StartCoroutine(decisionBot.generateDecisionBotPlan());
        //// Inner Bot
        //yield return StartCoroutine(innerBot.verifyPlan());

        //// Save new image pic and call Outer bot to verify
        //yield return StartCoroutine(cam.SaveImage());  // This increases the image counter locally first to save new image and we update the main.imageCounter to read this new image
        //main.imageCounter += 1;

        // Before calling, call scene descriptor and check if output is NO. If yes, then break out of the while loop
        //sceneDescriptor.generateSceneDescription();
        //if (sceneDescriptor.output.Contains("NO"))
        //{
        //    Debug.Log("[OUTER BOT] -- Fatal Scene Error Detected. Terminating Process.");
        //    // Set the totalReplanAttempts to -1 as we want to termiante
        //    main.totalReplanAttempts = -1;
        //    yield break;
        //}

        //// Outer Bot
        //yield return StartCoroutine(outerBot.verifyTaskCompletion());

        // Main entry point

        // TEST ONLY: Remove below line
        main.totalReplanAttempts = 15;   // This means we only call API once so not stuck in loop for testing.
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
                Debug.Log("total replan attempts = " + main.totalReplanAttempts);
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

                // TODO: REMOVE THIS
                // yield break;

                // Inner Bot -- Using ReplanVLM, it verifies entire plan and tells us NO if invalid.
                // NOTE: REPLAN VLM PAPER DOESN'T NEED IMAGE FOR INNERBOT VERIFICATION so we didn't call main.imageCounter++ or cam.SaveImage()
                yield return StartCoroutine(innerBot.verifyPlan(false));
                main.totalReplanAttempts -= 1;
            } while (innerBot.verdict.Contains("NO") && main.totalReplanAttempts >= 0);
            if (main.totalReplanAttempts < 0)
            {
                break;
            }
            Debug.Log("PLAN IS VERIFIED AND VALID!");

            // NOTE: Since the plan is verified, we reset the feedback from inner bot as it doesn't apply to any planning mistake in terms of verification.
            // If anything, the outer bot will flag it for us.
            innerBot.output = "";


            // Plan is VALID -- Execute motor function 
            // (For now execute, all functions and later make it so after each transfer level, we check outer bot i.e after each H1)

            Debug.Log("[Robot Controller] -- Executing Functions now");

            if (string.IsNullOrEmpty(main.prevState))
            {
                main.prevState = main.initialSceneDesc;
            }

            if (main.subtaskFunctions.Count == 0)
            {
                Debug.LogWarning("No functions to execute. Skipping execution phase and proceeding to OuterBot Verification of states.");
                yield return StartCoroutine(cam.SaveImage());  // This increases the image counter locally first to save new image and we update the main.imageCounter to read this new image
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

                // Only take the first line (before "REASON :" or any newlines)
                string[] verdictLines = rawVerdict.Split(new[] { '\n', '\r' }, StringSplitOptions.RemoveEmptyEntries);
                string verdict = verdictLines[0].Trim();

                // Since we have completed the API call for OuterBot, update prevState to equal currState Desc
                main.prevState = sceneDescriptor.output;

                Debug.Log("OUTER BOT FEEDBACK VALUE = " + verdict);
                Debug.Log($"[OUTERBOT] Raw verdict: '{rawVerdict}'");
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
                // Note - You dont need to call scene desc or capture image of scene since all actions in subtaks executed so you already have the updated state data in sceneDesc.output var

                // [Check #1] -- Save new image pic and call Scene Desc to check if state is still valid
                yield return StartCoroutine(cam.SaveImage());  // This increases the image counter locally first to save new image and we update the main.imageCounter to read this new image
                main.imageCounter += 1;
                yield return StartCoroutine(sceneDescriptor.generateSceneDescription());
                if (sceneDescriptor.output.Contains("NO"))
                {
                    Debug.Log("[SceneDescriptor] -- Non-Recoverable Scene Error Detected. Terminating Process.");
                    // Set the totalReplanAttempts to -1 as we want to termiante
                    main.totalReplanAttempts = -1;
                    yield break;
                }

                // [Check #2] -- Outer Bot subtask verification
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
                // if (idx > 0)
                // {
                //     prev_action = main.h1OnlyFunctionList[idx - 1];
                // }

                bool all_actions_executed = (idx == main.h1OnlyFunctionList.Count - 1);

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

                // Only take the first line (before "REASON :" or any newlines)
                string[] verdictLines = rawVerdict.Split(new[] { '\n', '\r' }, StringSplitOptions.RemoveEmptyEntries);
                string verdict = verdictLines[0].Trim();

                // Since we have completed the API call for OuterBot, update prevState to equal currState Desc
                main.prevState = sceneDescriptor.output;

                Debug.Log("OUTER BOT FEEDBACK VALUE = " + verdict);
                Debug.Log($"[OUTERBOT] Raw verdict: '{rawVerdict}'");
                Debug.Log($"[OUTERBOT] Cleaned verdict line: '{verdict}'");

                if (verdict.Contains("SUBTASK SUCCESS"))
                {
                    Debug.Log("Subtask completed successfully. Onto the next subtask!");

                    continue;

                }

                if (verdict.Contains("TASK SUCCESS"))
                {
                    // If we reach here, then that means the task has been executed successfully
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
                // outerBot.output = "";
                // outerBot.lastResponseId = null;
                // sceneDescriptor.lastResponseId = null;
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

        // OLD INNER BOT CODE BELOW
        // while ((main.index <= main.subtaskGoalstates.Count - 1) && (innerBot.verdict != "" && innerBot.verdict != "INVALID"))
        // {
        //     // If we take action after each subtask verification, then before next subtask verification, we need to execute the action
        //     // and call scene descriptor on the updated state.
        //     // TODO: See above comment
        //     yield return StartCoroutine(innerBot.verifyPlan(main.index));
        //     main.index += 1;
        // }

        // // TODO: When you call snipCam before passing updated image to InnerBot and OuterBot, make sure to add below line
        // main.imageCounter += 1;
        // if (innerBot.verdict == "INVALID")
        // {
        //     // Replan
        //     main.totalReplanAttempts -= 1;
        //     continue;
        // }

    }
}
