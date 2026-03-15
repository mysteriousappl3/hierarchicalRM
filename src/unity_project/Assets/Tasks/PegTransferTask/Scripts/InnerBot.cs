using UnityEngine;
using System.Collections.Generic;
using UnityEngine.Networking;
using System.Collections;
using System.IO;
using System;

public class InnerBot : MonoBehaviour
{
    [SerializeField]
    private Texture2D sceneImage;

    public DecisionBot decisionBot;
    public Main main;
    public H1ActionGenerator h1ActionGenerator;
    public H2ActionGenerator h2ActionGenerator;
    public SceneDescriptor sceneDescriptor;
    public StateDescriptor stateDescriptor;

    // TODO [Team Discussion]
    // 1. The InnerBot is not a VLM but instead doing a JSON comparison based verification?
    // 2. Confirm the pathway in the modified architecture as what inputs exactly feed into the InnerBot and what we expect it to output
    // 3. Is State Description fed into it as input to which we apply action and compare future states?
    // 4. The architecture shows Action Aggregator feeds into InnerBot. We are also passing the DecisionBot plan right?

    public string output;
    public string promptTemplateState;
    public string promptTemplate;

    public string verdict = "";


    void Start()
    {

        output = "";

        // TODO: Use InnerBot prompt from ReplanVLM i.e language based verification

        // TODO -- Based on the discussion for questions above, paste the InnerBot prompt below including any new information like future states in prompt with
        // placeholder {future_states} replaced via string.Replace()
        //prompt = @"
        //    Prompt for inner bot:

        //    You are misjudgement robot, and your main job is to determine whether the given subtasks in natural language and
        //    their sequence of robot action function calls passed from Decision Bot are correct in the current environment.
        //    Add a field in your response called RESULT: and if the subtasks are correct, reply with YES. If they are incorrect, reply
        //    with NO and have a field called REASON: and give your reason. If the plan is correct, have the reason as N/A.




        //    Check that the goal state matches the intention of the subtask interpreted in natural language.
        //    If not, state the discrepancy and do nothing else. Otherwise, check that the current state matches the subtask goal state.
        //    If not, find out what goes wrong in the action sequence and give an explanation.
        //    Next, check if the action sequence is valid (eg correct objects, correct parameters, no redundant action, each action can be
        //    carried out as expected). If constraints are present, check that in every state change the action sequence does not violate the
        //    constraints. If this is the last subtask, check that the subtask goal state matches the final goal state.

        //    Summarize the error in one paragraph if there’s any. Otherwise, just say “no error”.

        //    -----------------
        //    Example user input:

        //    This is the last subtask: NO
        //    Initial state: {“<peg_red>“: [], “<peg_green>“: [], “<peg_blue>“: [], “<ring_white>“: [“in(<peg_red>)“], “<ring_yellow>“: [“above(<ring_white>)“, “in(<peg_red>)“], “<ring_brown>“: [“above(<ring_yellow>)“, “in(<peg_red>)“]}
        //    Current state: {‘<peg_red>‘: [], ‘<peg_green>‘: [], ‘<peg_blue>‘: [], ‘<ring_white>’: [‘in(<peg_red>)‘], ‘<ring_yellow>’: [‘in(<peg_green>)‘], ‘<ring_brown>’: [‘in(<peg_green>)’, ‘above(<ring_yellow>)’]}
        //    Subtask goal state: {“<ring_yellow>“: [“in(<peg_green>)“], “<ring_brown>“: [“in(<peg_green>)“, “above(<ring_yellow>“]}
        //    Subtask goal state (in natural language): Move yellow and brown hoops from red to green, clearing red for white
        //    Final goal state: {​“<ring_white>“: [“in(<peg_blue>)“],​ “<ring_yellow>“: [“in(<peg_blue>)“, “above(<ring_white>)“],​ “<ring_brown>“: [“in(<peg_blue>)“, “above(<ring_yellow>)“]​}
        //    Final goal state (natural language): Following the rules of tower of hanoi, stack all the rings onto the blue peg
        //    Constraints: {​“<ring_white>“: [​“NOT(above(<ring_yellow>))“,​ “NOT(above(<ring_brown>))“​],​ “<ring_yellow>“: [​“NOT(above(<ring_brown>))“​], “<ring_brown>“: []​}

        //    Action sequence: MoveLowerHoop(<pillar_red>, <pillar_green>, <pillar_blue>)

        //    Here are the H1 functions:

        //    def MoveHoop(source_pillar, target_pillar):
        //       Move(source_pillar) # Move above the source pillar
        //       Grab() # Pick up the top grabbable hoop
        //       Move(target_pillar) # Move above the target pillar
        //       Drop() # Drop the hoop onto the target pillar

        //    Here are the H2 level functions:

        //    def SwapHoops(pillar1, pillar2, temp_pillar):
        //       MoveHoop(pillar1, temp_pillar)
        //       MoveHoop(pillar2, pillar1)
        //       MoveHoop(temp_pillar, pillar2)

        //    def MoveLowerHoop(source_pillar, target_pillar, temp_pillar):
        //       MoveHoop(source_pillar, temp_pillar)
        //       MoveHoop(source_pillar, target_pillar)
        //       MoveHoop(temp_pillar, target_pillar)



        //    Now, solve the task for the following information:
        //    Initial State: {initial_state}
        //    Current State: {current_state}  # TODO: Expected state we hope to reach from executing actions seq using action state transition (use same prompt from replanVLM to get this state)
        //    Subtask goal state: {subtask_goal_state}
        //    Subtask goal state (in natural language): {goal_state_nl}
        //    Final goal state: {final_goal_state}
        //    Final goal state (in natural language): {user_instruction}
        //    Constraints: {env_constraints}

        //    Action Sequence: {action_seq}

        //    H1 Actions: {h1_actions}
        //    H2 Actions: {h2_actions}


        //    In your output, be sure to add a field titled ""Verdict = "" and only output single word VALID for successful subtask verification and INVALID if
        //    there are any errors in the proposed plan.

        //    Be sure to wrap the Verdict within a ```start_verdict and ```end_verdict flag for parsing purposes.
        //    ";

        promptTemplateState = @"

            You are misjudgement robot, and you need to:
                Given the user instruction in natural language, check that the given goal state and constraints match the intention of the user instruction.
                For constraints, make sure following them in any state does not result in the user instruction being violated.
                If the goal state and/or constraints do not satisfy the user instruction, you must reply with NO and describe the reason behind in 3 to 4 sentences. 
                Assume current state given does not violate any rules or constraints in the user instruction.
               
            Add a field in your response called RESULT: and if the job are correct, reply with YES. If the job is incorrect, reply
            with NO and have a field called REASON: and give your reason which should be 3 to 4 sentences. If the job is correct, have the reason as N/A.

            It is very important to wrap the RESULT within a ```start_result and ```end_result flag for parsing purposes.
            For example,
            ```start_result
            RESULT: ...
            REASON: ...
            ```end_result

            Now, solve the task for the following information:
            Current state: {current_state}
            Goal State natural language: {user_instruction}
            Goal State and constraints in JSON: {state_description}
        ";

        // promptTemplateState = @"

        //     You are misjudgement robot, and you need to:
        //         Given the user instruction in natural language, check that the given goal state match the intention of the user instruction.
        //         If the goal state does not satisfy the user instruction, you must reply with NO and describe the reason behind in 3 to 4 sentences. 

        //     Add a field in your response called RESULT: and if the job are correct, reply with YES. If the job is incorrect, reply
        //     with NO and have a field called REASON: and give your reason which should be 3 to 4 sentences. If the job is correct, have the reason as N/A.

        //     It is very important to wrap the RESULT within a ```start_result and ```end_result flag for parsing purposes.
        //     For example,
        //     ```start_result
        //     RESULT: ...
        //     REASON: ...
        //     ```end_result

        //     Now, solve the task for the following information:
        //     Current state: {current_state}
        //     Goal State natural language: {user_instruction}
        //     Goal State in JSON: {state_description}
        // ";

        promptTemplate = @"
            Prompt for inner bot:

            You are misjudgement robot, and your main job is to determine whether the given subtasks in natural language and
            their sequence of robot action function calls passed from Decision Bot are correct in the current environment.
            Add a field in your response called RESULT: and if the subtasks are correct, reply with YES. If they are incorrect, reply
            with NO and have a field called REASON: and give your reason. If the plan is correct, have the reason as N/A.
            Also, make sure to check that the functions used in the plan are logically correct by looking at the function definitions provided.

            It is very important to wrap the RESULT within a ```start_result and ```end_result flag for parsing purposes.
            For example,
            ```start_result
            RESULT: ...
            REASON: ...
            ```end_result

            In addition, you will be given the current state JSON representation along with environment constraints for the task.
            You will also be given the function definitions at hierarchy level H2 and then at a lower level of H1 which are composed of the primitive
            actions of H0.

            Now, solve the task for the following information:
            Current State: {current_state}
            Goal State natural language: {user_instruction}
            Goal State and constraints in JSON: {state_description}

            H1 Functions: {h1_actions}
            H2 Functions: {h2_actions}

            Decision Bot Plan with Subtasks and Function execution: {decision_bot_output}
            ";

    }

    public IEnumerator verifyPlan(bool isStateDesc)
    {
        // TODO -- Make it dynamic instead of static _2 for index of scene image. Save state variable in main class.
        // string filePath = Path.Combine(Application.dataPath, $"Tasks/PegTransferTask/Task_Images/SceneImage_{main.imageCounter}.png");

        // if (File.Exists(filePath))
        // {
        //     byte[] imageData = File.ReadAllBytes(filePath);

        //     Texture2D texture = new Texture2D(2, 2); // size ignored; overwritten by LoadImage
        //     if (texture.LoadImage(imageData))
        //     {
        //         Debug.Log("Successfully loaded image into Texture2D");
        //         sceneImage = texture;  // assign to your existing variable
        //     }
        //     else
        //     {
        //         Debug.LogError("Failed to load image data into texture.");
        //         yield break;
        //     }
        // }

        //if (userInstruction == "")
        //{
        //    Debug.Log("[InnerBot] -- Empty user instruction!");
        //    return;
        //}

        //string currentState = sceneDescriptor.output;

        //if (currentState == "")
        //{
        //    Debug.Log("[InnerBot] -- Please generate current state scene description");
        //    return;
        //}

        //string initialState = main.initialStateDesc;

        //if(initialState == "")  
        //{
        //    Debug.Log("[InnerBot] -- Initial State Description is empty!");
        //    return;
        //}

        //string envConstraints = main.envConstraint;

        //if (envConstraints == "")
        //{
        //    Debug.Log("[InnerBot] -- Env Constraints is Empty!");
        //    return;
        //}

        //// TODO [Elsie] -- What's the datatype for action aggregator next states? Is this a List<string> where string denotes the state rep JSON?
        //List<string> futureStateDescriptors = actionAggregator.futureStateDescriptions;

        //if (futureStateDescriptors.Count == 0)
        //{
        //    Debug.Log("[InnerBot] -- Please ensure you generate future states before verifying the plan.");
        //    return;
        //}

        //// TODO OLD: Add function to extract for the 'index' subtask the action sequence.
        //// todo new: I think we pass the entire sequence of actions to this. Confirm with Elsie.
        //string actionSeq = "";

        //string h1Actions = h1ActionGenerator.output;

        //if (h1Actions == "")
        //{
        //    {
        //        Debug.Log("[InnerBot] -- H1 Actions empty!");
        //        return;
        //    }
        //}

        //string h2Actions = h2ActionGenerator.output;

        //if (h2Actions == "")
        //{
        //    {
        //        Debug.Log("[InnerBot] -- H2 Actions empty!");
        //        return;
        //    }
        //}

        //// TODO: Determine how you will extract the future state to pass into the innerbBot prompt.
        //int index = 0; // Placeholder. To be removed
        //string subtaskGoalState = futureStateDescriptors[index];

        //string finalGoalState = futureStateDescriptors[futureStateDescriptors.Count - 1];

        //// TODO: Extract from decision bot the subtask goal state for 'index' iteration. Add a parsing function
        //string subtaskGoalNL = "";

        string userInstruction = main.userInstruction;

        // string initialSceneDesc = @"
        // {
        //     ""objects"": [
        //         ""<peg_green>"",
        //         ""<hoop_yellow>"",
        //         ""<hoop_white>"",
        //         ""<hoop_purple>"",
        //         ""<peg_red>"",
        //         ""<peg_blue>""
        //     ],
        //     ""object_properties"": {
        //         ""<peg_green>"": [],
        //         ""<hoop_yellow>"": [""GRABBABLE""],
        //         ""<hoop_white>"": [""GRABBABLE""],
        //         ""<hoop_purple>"": [""GRABBABLE""],
        //         ""<peg_red>"": [],
        //         ""<peg_blue>"": []
        //     },
        //     ""spatial_relations"": {
        //         ""<peg_green>"": [],
        //         ""<hoop_yellow>"": [""in(<peg_green>)"", ""above(<hoop_white>)""],
        //         ""<hoop_white>"": [""in(<peg_green>)"", ""above(<hoop_purple>)""],
        //         ""<hoop_purple>"": [""in(<peg_green>)""],
        //         ""<peg_red>"": [],
        //         ""<peg_blue>"": []
        //     },
        //     ""your_explanation"": ""I included three hoops (yellow, white, purple) that are on the green peg, along with two additional pegs (red and blue). Each hoop is in the green peg, and the yellow hoop is above the white, which is above the purple, showing their stacked order. There are no other objects in the scene.""
        // }";

        // initialState = main.initialSceneDesc;

        // string h1Actions = @"
        //     public void MoveHoop(string hoop, string target)
        //     {
        //         Move(hoop);
        //         Grab();
        //         Move(target);
        //         Drop();
        //     }
        //     ";

        string h1Actions = h1ActionGenerator.output;

        // string h2Actions = @"
        //     public void MoveTwoHoops(string hoop1, string hoop2, string targetPeg)
        //     {
        //         MoveHoop(hoop1, targetPeg);
        //         MoveHoop(hoop2, targetPeg);
        //     }

        //     public void MoveThreeHoops(string hoop1, string hoop2, string hoop3, string targetPeg)
        //     {
        //         MoveHoop(hoop1, targetPeg);
        //         MoveHoop(hoop2, targetPeg);
        //         MoveHoop(hoop3, targetPeg);
        //     }

        //     public void SwapHoopsBetweenPegs(string hoop1, string peg1, string hoop2, string peg2)
        //     {
        //         MoveHoop(hoop1, peg2);
        //         MoveHoop(hoop2, peg1);
        //     }
        //     ";

        string h2Actions = h2ActionGenerator.output;

        // string envConstraints = @"
        //         constraint_spatial_relations"": {
        //                 ""ring_purple"": [
        //                     ""NOT(above(ring_purple, ring_white))"",
        //                     ""NOT(above(ring_purple, ring_yellow))""
        //                         ],
        //                 ""ring_white"": [
        //                     ""NOT(above(ring_white, ring_yellow))""
        //                 ],
        //                 ""ring_yellow"": []
        //                     }";

        string stateDescription = main.stateDescription;

        // Final goal state of entire task so last element 
        // string finalGoalState = @"
        //             {
        //               ""peg_blue"": [],
        //               ""peg_green"": [],
        //               ""peg_red"": [""ring_purple"", ""ring_white"", ""ring_yellow""]
        //             }";

        // Take the last subtask's goal state
        // finalGoalState = main.subtaskGoalstates[main.subtaskGoalstates.Count - 1];

        // string currentSceneDesc = @"
        //     {
        //       ""objects"": [
        //         ""peg_red"",
        //         ""peg_green"",
        //         ""peg_blue"",
        //         ""ring_white"",
        //         ""ring_yellow"",
        //         ""ring_purple""
        //       ],
        //       ""object_properties"": {
        //         ""peg_red"": [],
        //         ""peg_green"": [],
        //         ""peg_blue"": [],
        //         ""ring_white"": [""GRABBABLE""],
        //         ""ring_yellow"": [""GRABBABLE""],
        //         ""ring_purple"": [""GRABBABLE""]
        //       },
        //       ""spatial_relations"": {
        //         ""peg_red"": [],
        //         ""peg_green"": [],
        //         ""peg_blue"": [],
        //         ""ring_purple"": [
        //           ""in(peg_green)""
        //         ],
        //         ""ring_white"": [
        //           ""in(peg_green)""
        //           ""above(ring_purple)""
        //         ],
        //         ""ring_yellow"": [
        //           ""in(peg_green)"",
        //           ""above(ring_white)""
        //         ]
        //       }
        //     }";
        // ASSUMPTION -- We already ran sceneDescriptor on new scene image via cam.SaveImage() function in the DropDownAPI class
        string currentSceneDesc = sceneDescriptor.output;

        // string subtaskGoalNL = "Move the top 2 rings to temporary peg";

        // subtaskGoalNL = main.subtaskDescriptions[idx];

        // string subtaskGoalState = @"
        //             {
        //               ""blue"": [""ring_purple""],
        //               ""green"": [""ring_yellow"", ""ring_white""],
        //               ""red"": []
        //             }";

        // subtaskGoalState = main.subtaskGoalstates[idx];

        // Action Seq is for the specific subtask we are verifying. So this whole InnerBot needs to run one call after another in driver code.
        // Eg: If there are 5 subtask, then innerbot API called 5 times.
        // For testing, I used subtaks 1 from deciison bot.

        // string actionSeq = @"MoveHoop(""hoop_yellow"", ""peg_red""),
        //                      MoveHoop(""hoop_white"", ""peg_blue""),
        //                      MoveHoop(""hoop_yellow"", ""peg_blue"")";

        string decisionBotOutput = decisionBot.output;

        // actionSeq = string.Join(", ", main.subtaskFunctions[idx]);

        // TODO: Make DecisionBot structure all the required info as json of json and you can access relevant details from the key
        //prompt = prompt
        //            .Replace("{initial_state}", initialSceneDesc)
        //            .Replace("{current_state}", currentSceneDesc)
        //            .Replace("{subtask_goal_state}", subtaskGoalState)
        //            .Replace("{goal_state_nl}", subtaskGoalNL)
        //            .Replace("{final_goal_state}", finalGoalState)
        //            .Replace("{user_instruction}", userInstruction)
        //            .Replace("{env_constraints}", envConstraints)
        //            .Replace("{action_seq}", actionSeq)
        //            .Replace("{h1_actions}", h1Actions)
        //            .Replace("{h2_actions}", h2Actions);

        Debug.Log("[InnerBot] State Descriptor output: " + stateDescription);
        string prompt;
        if (isStateDesc)
        {
            prompt = promptTemplateState
                    .Replace("{current_state}", currentSceneDesc)
                    .Replace("{user_instruction}", userInstruction)
                    .Replace("{state_description}", stateDescription);
        }
        else
        {
            prompt = promptTemplate
                    .Replace("{current_state}", currentSceneDesc)
                    .Replace("{state_description}", stateDescription)
                    .Replace("{user_instruction}", userInstruction)
                    .Replace("{h1_actions}", h1Actions)
                    .Replace("{h2_actions}", h2Actions)
                    .Replace("{decision_bot_output}", decisionBotOutput);
        }

        yield return StartCoroutine(CallOpenAIAPI(prompt));

    }

    IEnumerator CallOpenAIAPI(string prompt)
    {
        string APIKey = main.getOpenAIAPIKey();
        string APIurl = main.getOpenAIAPIURL();

        // // Convert image to PNG and then Base64
        // byte[] imageBytes = image.EncodeToPNG();
        // string base64Image = System.Convert.ToBase64String(imageBytes);

        // Escape prompt string for JSON
        string escapedPrompt = prompt.Replace("\\", "\\\\")
                                            .Replace("\"", "\\\"")
                                            .Replace("\n", "\\n")
                                            .Replace("\r", "\\r");

        // Build JSON request body
        string jsonRequest = $@"{{
            ""model"": ""o4-mini"",
            ""messages"": [
                {{
                    ""role"": ""system"",
                    ""content"": ""You are verifier VLM responsible for verifying for the given user subtask information and determining whether the subtask goal has been completed or not.""
                }},
                {{
                    ""role"": ""user"",
                     ""content"": [
                        {{ ""type"": ""text"", ""text"": ""{escapedPrompt}"" }}
                    ]
                }}
            ],
            ""max_completion_tokens"": 20000,
            ""reasoning_effort"": ""high""
        }}";

        UnityWebRequest request = new UnityWebRequest(APIurl, "POST");
        byte[] bodyRaw = System.Text.Encoding.UTF8.GetBytes(jsonRequest);
        request.uploadHandler = new UploadHandlerRaw(bodyRaw);
        request.downloadHandler = new DownloadHandlerBuffer();

        request.SetRequestHeader("Content-Type", "application/json");
        request.SetRequestHeader("Authorization", $"Bearer {APIKey}");

        Debug.Log("[InnerBot] Sending OpenAI API Request...");
        yield return request.SendWebRequest();
        Debug.Log("[InnerBot] Received API Response.");

        if (request.result != UnityWebRequest.Result.Success)
        {
            Debug.LogError($"[InnerBot] API Request Failed: {request.error}\n{request.downloadHandler.text}");
        }
        else
        {
            string jsonResponse = request.downloadHandler.text;

            OpenAIResponse response = JsonUtility.FromJson<OpenAIResponse>(jsonResponse);

            Debug.Log("[InnerBot] Raw API response:\n" + jsonResponse);

            if (response.choices != null && response.choices.Length > 0)
            {
                output = response.choices[0].message.content.Trim();
                Debug.Log("[InnerBot] OpenAI Output:\n" + output);

                output = main.ExtractBetweenFlags(output, "```start_result", "```end_result");
                main.innerbot_feedback = output;

                Debug.Log("EXTRACTED Inner Bot result: ");

                // Extract substring after "RESULT:" string
                int index = output.IndexOf("RESULT:");
                if (index != -1)
                {
                    string resultLine = output.Substring(index + "RESULT:".Length).Trim();
                    string[] lines = resultLine.Split(new[] { '\n', '\r' }, StringSplitOptions.RemoveEmptyEntries);
                    verdict = lines[0].Trim();
                    Debug.Log("RESULT = " + verdict);
                }
                else
                {
                    Debug.LogWarning("RESULT string not found in output.");
                }
            }
            else
            {
                Debug.LogError("[InnerBot] OpenAI API returned empty choices or malformed response.");
            }
        }
    }

    // Response wrapper for JsonUtility
    [System.Serializable]
    private class OpenAIResponse
    {
        public Choice[] choices;
    }

    [System.Serializable]
    private class Choice
    {
        public Message message;
    }

    [System.Serializable]
    private class Message
    {
        public string role;
        public string content;
    }

}
