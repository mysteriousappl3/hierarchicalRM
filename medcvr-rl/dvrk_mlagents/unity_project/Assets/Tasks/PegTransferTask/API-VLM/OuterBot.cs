using UnityEngine;
using System.Collections.Generic;
using System.Text.RegularExpressions;
using UnityEngine.Networking;
using System.Collections;
using System.IO;
using System;
using System.Text;
using System.Linq;

public class OuterBot : MonoBehaviour
{
    public SnipCameraScript snipCamera;

    public SceneDescriptor sceneDescriptor;
    public Main main;

    public H1ActionGenerator h1ActionGenerator;

    public Texture2D sceneImage;

    public string sceneDescription;

    public string output;
    public string promptTemplate;
    public string feedback;

    public string systemPrompt;
    public string replanVlmPrompt;

    public string lastResponseId = null;

    void Start()
    {

        // NOTE: NOT USED
        systemPrompt = @"
            You are a robot that detects execution errors in H1 actions.
            Definitions:
            • SUCCESS: current state == goal state.
            • EXECUTE REMAINING ACTIONS: valid state but goal not reached.
            • RECOVERABLE: minor glitch—-retry the same action.
            • NON-RECOVERABLE: major error—-replan.

            State terms:
            • “current state” = scene just before the action.
            • “next state”    = scene immediately after the action.
            • Lists are bottom-up, left-to-right (top hoop = last element).
            • Always validate exactly the hoop moved by the given action.
            • Refer only to JSON keys (e.g. `<hoop_pink>`).  
            If two look similar (pink/purple), treat them as the same hoop.

            Defined H1 Actions:

            {h1_actions}

            Wrap your answer exactly as:

            ```start_error_type
            Error : <SUCCESS|EXECUTE REMAINING ACTIONS|RECOVERABLE|NON-RECOVERABLE>
            Reason : <brief explanation>
            ```end_error_type

        ";

        output = "";
        feedback = "";


        // prompt = @"
        //     You are a robot that detects execution errors. You need to verify the state representation after the execution of a
        //     state transfer (ie H1 action) to determine whether the target state is fulfilled.
        //     If there is any execution error resulting in the target state not fulfilled, describe and identify it as one of the two
        //     types below and give a clear justification on your choice. If the target state and current state JSON representations are equivalent for the hoops placement in respective pegs,
        //     this means the task is fulfilled and there is no execution error so reply with “SUCCESS”.

        //     There are TWO types of errors, which are listed below:
        //     1. Recoverable error:
        //     After the state transition (ie the H1 action) gets executed again, there should be no more error.
        //     This means only very minor error should be considered as recoverable error.
        //     2. Non-recoverable error (Correction possible):
        //     The current state transition is invalid and the action being executed cause major errors.
        //     However, the state is still valid and interpretable by the state representation dictionary.
        //     In this case, the decision bot should be able to replan from the original state (the state before this error occurs).

        //     You will also be given information whether all actions have been executed. 
        //     You need to take the JSON representation of previous state, current state and goal state and determine
        //     whether there is any errors that took place considering the status of whether all actions have been executed.

        //     If at any point, you observe any major recoverable errors or non-recoverable error, flag them.
        //     Otherwise, consider whether the task has been completed or not given user input and function execution status.

        //    It is important to remember that:
        //     • “current state” = scene just before the action.  
        //     • “next state”   = scene immediately after that action.  
        //     Always compare current state and next against the goal.  

        //     We specify these two states as part of the prompt so you can reason how the objects in the scene move between states and how that ties to the response you return.

        //     Refer only to JSON keys (e.g. `<hoop_pink>`), not plain colour words.  
        //     If two keys look similar (pink/purple), they represent the same hoop.  

        //     In the state description, the state objects are ordered bottom-up, left-to-right order. 
        //     This means that the top hoop is the last element in the list
        //     Be sure to carefully consider the spatial relations. 

        //     We always move the top most hoop by definition in our environment.

        //     A peg is the same as a pillar in our environment.

        //     Here's an example for user instruction in outer bot:

        //     Current state before executing latest action MoveHoop(""peg_green"", ""peg_red"") : {‘<peg_red>‘: [], ‘<peg_green>‘: [], ‘<peg_blue>‘: [], ‘<hoop_white>’: [‘in(<peg_red>)‘], ‘<hoop_yellow>’: [‘above(<hoop_white>)’, ‘in(<peg_red>)‘], ‘<hoop_purple>’: [‘in(<peg_green>)‘]}
        //     Next state after executing latest action MoveHoop(""peg_green"", ""peg_red"") : {‘<peg_red>‘: [], ‘<peg_green>‘: [], ‘<peg_blue>‘: [], ‘<hoop_white>’: [‘in(<peg_red>)‘], ‘<hoop_yellow>’: [‘in(<peg_blue>)‘], ‘<hoop_purple>’: [‘in(<peg_green>)‘]}
        //     Final Goal state: {‘<peg_red>‘: [], ‘<peg_green>‘: [], ‘<peg_blue>‘: [], ‘<hoop_white>’: [‘in(<peg_red>)‘], ‘<hoop_yellow>’: [‘above(<hoop_white>)’, ‘in(<peg_red>)‘], ‘<hoop_purple>’: [‘in(<peg_blue>)’]}
        //     Environment Constraints:  ""constraint_spatial_relations"": {
        //             ""hoop_purple"": [
        //                 ""NOT(above(hoop_purple, hoop_white))"",
        //                 ""NOT(above(hoop_purple, hoop_yellow))""
        //             ],
        //             ""hoop_white"": [
        //                 ""NOT(above(hoop_white, hoop_yellow))""
        //             ],
        //             ""hoop_yellow"": []
        //         }
        //     All actions executed in entire task: false
        //     Actions Executed So Far: MoveHoop(""peg_green"", ""peg_red"")


        //     Now using this, solve for the following task information:


        //     Current state before latest action {curr_action} : {prev_state}

        //     Next state after latest action {curr_action} : {current_state}

        //     Final Goal state : {goal_state}

        //     Environment Constraints: {env_constraint}

        //     All actions executed in entire task: {all_actions_executed}

        //     Sequence of Previous Actions Executed Since Initial State : {actions_executed_sofar}

        //     H1 Actions: {h1_actions}



        //     Your response must fall into one of the following categories, labeled under `Error :`:

        //     1. SUCCESS — The goal state and current state JSON representations are equivalent for hoops and peg placements. Hence the task is completed without errors.
        //     2. EXECUTE REMAINING ACTIONS — The current state is valid, and the robot appears to be progressing correctly toward the goal. Not all actions have been executed yet.
        //     3. RECOVERABLE — A minor, temporary issue has occurred that may be resolved by re-executing the last action.
        //     4. NON-RECOVERABLE — A major execution error has occurred that prevents the current plan from continuing successfully.

        //     Wrap your output inside the following flags so it can be parsed:

        //     ```start_error_type
        //     Error : <your choice here>
        //     Reason : <brief explanation why>
        //     ```end_error_type
        // ";

        promptTemplate = @"
            You are a vision language model that detects execution errors in subtask execution.
            You must reason about how objects move between previous and current state as a result of the specified subtask requirement.
            Based on this change of state information, determine which of the following error types the response falls under.
            Note that goal state refers to the expected state after ALL actions have been executed, not just the current action.
            The definitions are given below:

            Definitions:
            • TASK SUCCESS: current state == final goal state or equivalent representation.
                            You must output this when final subtask goal state is reached given that it is equivalent to the goal state.
            • SUBTASK SUCCESS: current state == subtask goal state or equivalent representation.
            • EXECUTE REMAINING ACTIONS: valid intermediate state but final goal state or subtask goal state not reached.
            • RECOVERABLE: Valid scene representation but subtask goal state not reached.
            • NON-RECOVERABLE: Major scene representation error or environment constraint violated. Requires human intervention.

            State terms:
            • prev state” = scene just before executing subtask.
            • curr state”    = scene immediately after executing subtask.
            • Refer only to JSON keys (e.g. `<object_pink>`).  
            
            Remember that the color of the objects defined in the goal state is what the environment contains. 
            If you observe similar looking colours between current state and previous state when compared to the goal state, 
            assume they refer to the same object and state this assumption in your reason.

            
            STRICT OUTPUT RULE (MUST FOLLOW EXACTLY):
            It is very important to wrap your answer exactly as below including the quotation mark:

            ```start_error_type
            Error : <TASK SUCCESS | SUBTASK SUCCESS | EXECUTE REMAINING ACTIONS | RECOVERABLE | NON-RECOVERABLE>
            Reason : <brief explanation>
            ```end_error_type

            Now solve for the following task information:

            Environment Constraint : {env_constraint}

            Subtask Requirement : {subtask_nl}

            prev_state before subtask execution: {prev_state}

            curr_state after subtask execution : {curr_state}

            subtask_goal_state : {subtask_goal_state}

            final_goal_state : {final_goal_state}

        ";

        replanVlmPrompt = @"
            You are a robot that detects errors. You need to compare the environmental information before and after 
            task execution to determine whether the task is completed. If it is completed, reply with YES. Otherwise, 
            reply with NO and explain the reason behind.

            The first image shows the environment before task execution, and the second image shows the environment 
            after task execution.

            Information from Decision Bot:
            Task requirement: {user_instruction}
            Decision Bot Plan: {decision_bot_output}
        ";
            
    }

    public IEnumerator verifyTaskCompletion(string subtaskNL, string subtaskGoalState, string finalGoalState)
    {
        Debug.Log("Prev State inside outer bot = " + main.prevState);

        // Debug.Log(" Previous state before executing latest action " + curr_action);
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
        // else
        // {
        //     Debug.LogError("Image file not found: " + filePath);
        // }

        // if (sceneImage == null)
        // {
        //     Debug.LogError("[SceneDescriptor] -- Please ensure to capture a screenshot of the scene.");
        //     yield break;
        // }

        string h1Actions = h1ActionGenerator.output;
        // // string initialSceneDesc = main.initialSceneDesc;
        string currentSceneDesc = sceneDescriptor.output;
        // List<string> futureStateDescriptions = actionAggregator.futureStateDescriptions;

        // sceneDescriptor.generateSceneDescription();

        // sceneDescription = sceneDescriptor.output;

        // if (sceneDescription == "")
        // {
        //     Debug.Log("[OuterBot] -- Error generatring scene description for the image");
        //     yield break;
        // }

        // TODO: Determine how you will iterate through this one by one to compare with the sceneDescription
        // TODO: If you do this programatically, then you have to call the snip function to get new state, call generateSceneDescription() again
        // and compare with next iteraton futureStateDescription.

        // TODO: OpenAI/Deepseek API call to pass 'prompt' sceneDescription and future state to model and store reuslt in 'output'




        // TODO: How will we differentiate between the type of output? Do we have a section called "Feedback Type:" and have VLM choose between the 4 types and have an "Explanation" field for each in its output?

        //Match match = Regex.Match(output, @"Feedback Type:\s*(\w+)");

        //if(!match.Success)
        //{
        //    Debug.Log("[OuterBot] -- Error finding the Feedback Type tag in Outer Bot result. Please ensure this field exists in the response from API.");
        //    yield break;
        //}

        // TODO: Notice the constraint that we only take the first word to determine the type of error we have.
        // string feedbackType = match.Groups[1].Value;

        //if (feedbackType == "Success")
        //{
        //    Debug.Log("SUCCESS -- The task instruction has been successfully completed");
        //    yield break;
        //}
        //else if (feedbackType == "Continue")    // TODO: Confirm if we use 'Continue' as a way to determine more actions are yet to run
        //{
        //    Debug.Log("Execute Remaining Action");
        //    yield break;
        //}
        //else if (feedbackType == "Recoverable")
        //{
        //    Debug.Log("Recoverable Error -- Execute previous action again");
        //    yield break;
        //}
        //// another case of non-recoverable error - if action doesnt complete within set timeout like whcih action caused timeout like MoveCoroutine. Also mention what it was tyring to do i.e parent
        //// H1 action function.
        //else if (feedbackType == "Non-Recoverable")
        //{
        //    // TODO: Make sure in prompt our field is called Explanation as well with same number of "
        //    Match explanationMatch = Regex.Match(output, @"""Explanation""\s*:\s*""([^""]*)""");

        //    if (!explanationMatch.Success)
        //    {
        //        Debug.Log("[OuterBot] -- Error finding explanation field for Decision Bot feedback.");
        //        yield break;
        //    }

        //    string explanation = explanationMatch.Groups[1].Value;
        //    feedback = explanation;

        //    Debug.Log("Non-Recoverable Error -- Needs to REPLAN from Decision Bot!");
        //    yield break;
        //}

        string env_constraint = main.envConstraint;

        // TODO: Need to pass context of previous action
        // Debug.Log("INSIDE OUTER BOT FUNCTION");

        // Debug.Log("OUTER BOT PREV STATE = " + prevState);
        // Debug.Log("OUTER BOT CURR STATE = " + currentSceneDesc);
        // Debug.Log("OUTER BOT GOAL STATE = " + goalState);
        // Debug.Log("OUTER BOT ALL FUNCTIONS EXECUTED = " + all_actions_executed);

        // string actionsSoFarString = string.Join(", ", actionsExecutedSoFar);
        // Debug.Log("OUTER BOT ACTIONS EXECUTED SO FAR = " + actionsSoFarString);

        // prompt = prompt
        //             .Replace("{curr_action}", curr_action)
        //             .Replace("{prev_state}", prevState)
        //             .Replace("{current_state}", currentSceneDesc)
        //             .Replace("{goal_state}", goalState)
        //             .Replace("{env_constraint}", env_constraint)
        //             .Replace("{all_actions_executed}", all_actions_executed.ToString())
        //             .Replace("{actions_executed_sofar}", actionsSoFarString)
        //             .Replace("{h1_actions}", h1Actions);


        //  prompt = prompt.Replace("{h1_actions}", h1Actions);

        string prompt = promptTemplate
                    .Replace("{env_constraint}", env_constraint)
                    .Replace("{subtask_nl}", subtaskNL)
                    .Replace("{prev_state}", main.prevState)
                    .Replace("{curr_state}", currentSceneDesc)
                    .Replace("{subtask_goal_state}", subtaskGoalState)
                    .Replace("{final_goal_state}", finalGoalState)
                    ;

        Debug.Log("PROMPT = " + prompt);

        // yield return StartCoroutine(CallOpenAIAPI(prompt));

        yield return StartCoroutine(CallGeminiAPI(prompt));
    }

    public IEnumerator verifyTaskCompletionReplanVlm(string decisionBotOutput)
    {
        string imagePath = Path.Combine(Application.dataPath, $"Tasks/PegTransferTask/Task_Images/SceneImage_{main.imageCounter-1}.png");
        string imagePath2 = Path.Combine(Application.dataPath, $"Tasks/PegTransferTask/Task_Images/SceneImage_{main.imageCounter}.png");
        yield return StartCoroutine(CallReplanVlmApi(imagePath, imagePath2, decisionBotOutput));
    }

    IEnumerator CallOpenAIAPI(string prompt)
    {
        string APIKey = main.getOpenAIAPIKey();
        string APIurl = main.getOpenAIReasoningURL(); // /v1/responses

        // 1) Prepare & escape your system and user text
        string escapedSystem = systemPrompt
            .Replace("\\", "\\\\")
            .Replace("\"", "\\\"")
            .Replace("\n", "\\n")
            .Replace("\r", "\\r");

        string escapedUser = prompt
            .Replace("\\", "\\\\")
            .Replace("\"", "\\\"")
            .Replace("\n", "\\n")
            .Replace("\r", "\\r");

        // 2) Conditionally include previous_response_id
        string prevIdPart = string.IsNullOrEmpty(lastResponseId)
            ? ""
            : $",\n    \"previous_response_id\": \"{lastResponseId}\"";

        // 3) Build the JSON request body manually
        string jsonRequest;
        // if (string.IsNullOrEmpty(lastResponseId))
        // {
        //     // First call: include both system + user
        //     jsonRequest = $@"{{
        //         ""model"": ""o3"",
        //         ""reasoning"": {{ ""effort"": ""medium"" }},
        //         ""input"": [
        //             {{
        //             ""role"": ""system"",
        //             ""content"": ""{escapedSystem}""
        //             }},
        //             {{
        //             ""role"": ""user"",
        //             ""content"": ""{escapedUser}""
        //             }}
        //         ]
        //     }}";
        // }
        // else
        // {
        //     // Subsequent calls: omit system, chain memory, send only user
        //     jsonRequest = $@"{{
        //         ""model"": ""o3"",
        //         ""reasoning"": {{ ""effort"": ""medium"" }}{prevIdPart},
        //         ""input"": [
        //             {{
        //             ""role"": ""user"",
        //             ""content"": ""{escapedUser}""
        //             }}
        //         ]
        //     }}";
        // }

        jsonRequest = $@"{{
                ""model"": ""o4-mini"",
                ""reasoning"": {{ ""effort"": ""high"" }},
                ""input"": [
                    {{
                    ""role"": ""system"",
                    ""content"": ""You are a execution error detection VLM who is responsible for comparing the JSON state representation and determine whether the task has been completed or there are other errors as described in the user prompt. You must first from the given previous state determine what the top most object is. The determined object is what the current action will be interacted on for previous state.""
                    }},
                    {{
                    ""role"": ""user"",
                    ""content"": ""{escapedUser}""
                    }}
                ]
            }}";

        // 4) Send HTTP POST
        UnityWebRequest request = new UnityWebRequest(APIurl, "POST");
        byte[] bodyRaw = Encoding.UTF8.GetBytes(jsonRequest);
        request.uploadHandler   = new UploadHandlerRaw(bodyRaw);
        request.downloadHandler = new DownloadHandlerBuffer();
        request.SetRequestHeader("Content-Type", "application/json");
        request.SetRequestHeader("Authorization", $"Bearer {APIKey}");

        Debug.Log("[OuterBot] Sending OpenAI Responses API Request...");
        yield return request.SendWebRequest();
        Debug.Log("[OuterBot] Received API Response.");

        if (request.result != UnityWebRequest.Result.Success)
        {
            Debug.LogError($"[OuterBot] API Request Failed: {request.error}\n{request.downloadHandler.text}");
            yield break;
        }

        // 5) Deserialize response
        string jsonResponse = request.downloadHandler.text;
        Debug.Log("[OuterBot] Raw API response:\n" + jsonResponse);
        var response = JsonUtility.FromJson<ResponsesAPIResponse>(jsonResponse);

        // 6) Save response ID
        lastResponseId = response.id;
        Debug.Log("LAST RESPONSE ID = " + lastResponseId);

        // 7) Extract assistant’s message text
        var msgBlock = response.output
            .FirstOrDefault(o => o.type == "message" && o.content != null);
        if (msgBlock == null)
        {
            Debug.LogError("[OuterBot] No message block found in response.output!");
            yield break;
        }

        var outputText = msgBlock.content
            .FirstOrDefault(c => c.type == "output_text")?.text;
        if (outputText == null)
        {
            Debug.LogError("[OuterBot] No output_text found in messageBlock.content!");
            yield break;
        }

        string content = outputText.Trim();
        output = content;
        Debug.Log("[OuterBot] OpenAI Output:\n" + content);

        // 8) Parse your error block
        string errorBlock = main.ExtractBetweenFlags(content,
                                                     "```start_error_type",
                                                     "```end_error_type");
        Debug.Log("EXTRACTED Outer Bot Error Block:\n" + errorBlock);

        // 9) Extract the Error type
        int index = errorBlock.IndexOf("Error :");
        if (index != -1)
        {
            feedback = errorBlock.Substring(index + "Error :".Length).Trim();
            Debug.Log("OUTERBOT VERDICT = " + feedback);
        }
        else
        {
            Debug.LogWarning("[OuterBot] Error type string not found in output block.");
        }
    }

    IEnumerator CallGeminiAPI(string prompt)
{
    string APIKey = main.getGeminiAPIKey();
    string APIurl = main.getGeminiAPIUrl();

    // 1) Prepare & escape your system and user text
    string escapedSystem = systemPrompt
        .Replace("\\", "\\\\")
        .Replace("\"", "\\\"")
        .Replace("\n", "\\n")
        .Replace("\r", "\\r");

    string escapedUser = prompt
        .Replace("\\", "\\\\")
        .Replace("\"", "\\\"")
        .Replace("\n", "\\n")
        .Replace("\r", "\\r");

    // 2) Conditionally include previous_response_id (Gemini doesn't support this; kept as-is but unused)
    string prevIdPart = string.IsNullOrEmpty(lastResponseId)
        ? ""
        : $",\n    \"previous_response_id\": \"{lastResponseId}\"";

    // 3) Build the JSON request body (Gemini)
    string jsonRequest;

    jsonRequest = $@"{{
        ""contents"": [
            {{
                ""role"": ""user"",
                ""parts"": [
                    {{ ""text"": ""You are a execution error detection VLM who is responsible for comparing the JSON state representation and determine whether the task has been completed or there are other errors as described in the user prompt. You must first from the given previous state determine what the top most object is. The determined object is what the current action will be interacted on for previous state."" }}
                ]
            }},
            {{
                ""role"": ""user"",
                ""parts"": [
                    {{ ""text"": ""{escapedUser}"" }}
                ]
            }}
        ],
        ""generationConfig"": {{
            ""temperature"": 0.0
        }}
    }}";

    // 4) Send HTTP POST
    UnityWebRequest request = new UnityWebRequest(APIurl, "POST");
    byte[] bodyRaw = System.Text.Encoding.UTF8.GetBytes(jsonRequest);
    request.uploadHandler = new UploadHandlerRaw(bodyRaw);
    request.downloadHandler = new DownloadHandlerBuffer();
    request.SetRequestHeader("Content-Type", "application/json");
    request.SetRequestHeader("x-goog-api-key", APIKey);

    Debug.Log("[OuterBot] Sending Gemini Request...");
    yield return request.SendWebRequest();
    Debug.Log("[OuterBot] Received API Response.");

    if (request.result != UnityWebRequest.Result.Success)
    {
        Debug.LogError($"[OuterBot] API Request Failed: {request.error}\n{request.downloadHandler.text}");
        yield break;
    }

    // 5) Read raw response
    string jsonResponse = request.downloadHandler.text;
    Debug.Log("[OuterBot] Raw API response:\n" + jsonResponse);

    // 6) Save response ID (Gemini responseId exists in JSON but we are not parsing classes; keep old behavior minimal)
    // lastResponseId is not updated here.

    // 7) Extract assistant’s message text using flags from raw response JSON
    const string startFlag = "```start_error_type";
    const string endFlag = "```end_error_type";

    int s = jsonResponse.IndexOf(startFlag, StringComparison.OrdinalIgnoreCase);
    if (s < 0)
    {
        Debug.LogError("[OuterBot] start_flag not found in Gemini response.");
        yield break;
    }

    int contentStart = s + startFlag.Length;

    int e = jsonResponse.IndexOf(endFlag, contentStart, StringComparison.OrdinalIgnoreCase);
    if (e < 0)
    {
        Debug.LogError("[OuterBot] end_flag not found in Gemini response.");
        yield break;
    }

    string between = jsonResponse.Substring(contentStart, e - contentStart);

    // Unescape common JSON escapes (because we sliced from inside JSON string)
    string content = between
        .Replace("\\n", "\n")
        .Replace("\\r", "\r")
        .Replace("\\t", "\t")
        .Replace("\\\"", "\"")
        .Replace("\\\\", "\\")
        .Trim();

    if (content.StartsWith("\n")) content = content.Substring(1).Trim();

    output = content;
    Debug.Log("[OuterBot] Gemini Output:\n" + content);

    // 8) Parse your error block
    // Extract error block between flags directly from raw response JSON
    const string startErr = "```start_error_type";
    const string endErr = "```end_error_type";

    int es = jsonResponse.IndexOf(startErr, StringComparison.OrdinalIgnoreCase);
    if (es < 0)
    {
        Debug.LogError("[OuterBot] start_error_type not found in Gemini response.");
        yield break;
    }

    int errStart = es + startErr.Length;

    int ee = jsonResponse.IndexOf(endErr, errStart, StringComparison.OrdinalIgnoreCase);
    if (ee < 0)
    {
        Debug.LogError("[OuterBot] end_error_type not found in Gemini response.");
        yield break;
    }

    string errBetween = jsonResponse.Substring(errStart, ee - errStart);

    string errorBlock = errBetween
        .Replace("\\n", "\n") 
        .Replace("\\r", "\r")
        .Replace("\\t", "\t")
        .Replace("\\\"", "\"")
        .Replace("\\\\", "\\")
        .Trim();

    if (errorBlock.StartsWith("\n")) errorBlock = errorBlock.Substring(1).Trim();

    Debug.Log("EXTRACTED Outer Bot Error Block:\n" + errorBlock);

    // 9) Extract the Error type
    int index = errorBlock.IndexOf("Error :");
    if (index != -1)
    {
        feedback = errorBlock.Substring(index + "Error :".Length).Trim();
        Debug.Log("OUTERBOT VERDICT = " + feedback);
    }
    else
    {
        Debug.LogWarning("[OuterBot] Error type string not found in output block.");
    }
}


    public IEnumerator CallReplanVlmApi(string imagePath1, string imagePath2, string decisionBotOutput)
    {
        // 1. Load both images from file
        if (!File.Exists(imagePath1))
        {
            Debug.LogError($"[ReplanVLM] Image file not found: {imagePath1}");
            yield break;
        }
        if (!File.Exists(imagePath2))
        {
            Debug.LogError($"[ReplanVLM] Image file not found: {imagePath2}");
            yield break;
        }

        byte[] imageData1 = File.ReadAllBytes(imagePath1);
        byte[] imageData2 = File.ReadAllBytes(imagePath2);
        string base64Image1 = Convert.ToBase64String(imageData1);
        string base64Image2 = Convert.ToBase64String(imageData2);
        Debug.Log($"[ReplanVLM] Loaded images: {imagePath1}, {imagePath2}");

        // 2. Prepare API credentials
        string APIKey = main.getOpenAIAPIKey();
        string APIurl = main.getOpenAIReasoningURL();

        // 3. Escape prompt
        replanVlmPrompt = replanVlmPrompt.Replace("{user_instruction}", main.userInstruction).Replace("{decision_bot_output}", decisionBotOutput);
        string escapedPrompt = replanVlmPrompt
            .Replace("\\", "\\\\")
            .Replace("\"", "\\\"")
            .Replace("\n", "\\n")
            .Replace("\r", "\\r");

        // 4. Assemble request body with both images
        string jsonRequest = $@"{{
            ""model"": ""o4-mini"",
            ""reasoning"": {{ ""effort"": ""high"" }},
            ""input"": [
                {{
                    ""role"": ""system"",
                    ""content"": ""You are a robot that detects errors. You need to compare the environmental information before and after task execution to determine whether the task is completed. If it is completed, reply with YES. Otherwise, reply with NO and explain the reason behind.""
                }},
                {{
                    ""role"": ""user"",
                    ""content"": [
                        {{
                            ""type"": ""input_text"",
                            ""text"": ""{escapedPrompt}""
                        }},
                        {{
                            ""type"": ""input_image"",
                            ""image_url"": ""data:image/png;base64,{base64Image1}""
                        }},
                        {{
                            ""type"": ""input_image"",
                            ""image_url"": ""data:image/png;base64,{base64Image2}""
                        }}
                    ]
                }}
            ]
        }}";

        // 5. Send request
        UnityWebRequest request = new UnityWebRequest(APIurl, "POST");
        byte[] bodyRaw = Encoding.UTF8.GetBytes(jsonRequest);
        request.uploadHandler = new UploadHandlerRaw(bodyRaw);
        request.downloadHandler = new DownloadHandlerBuffer();
        request.SetRequestHeader("Content-Type", "application/json");
        request.SetRequestHeader("Authorization", $"Bearer {APIKey}");

        Debug.Log("[ReplanVLM] Sending API Request...");
        yield return request.SendWebRequest();
        Debug.Log("[ReplanVLM] Received API Response.");

        // 6. Process response
        if (request.result != UnityWebRequest.Result.Success)
        {
            Debug.LogError($"[ReplanVLM] API Request Failed: {request.error}\n{request.downloadHandler.text}");
            yield break;
        }

        string jsonResponse = request.downloadHandler.text;
        Debug.Log("[ReplanVLM] Raw API response:\n" + jsonResponse);

        // Parse using the ResponsesAPIResponse class
        ResponsesAPIResponse response = JsonUtility.FromJson<ResponsesAPIResponse>(jsonResponse);

        OutputItem messageBlock = null;
        if (response != null && response.output != null)
        {
            foreach (var item in response.output)
            {
                if (item.type == "message")
                {
                    messageBlock = item;
                    break;
                }
            }
        }

        if (messageBlock == null || messageBlock.content == null || messageBlock.content.Length == 0)
        {
            Debug.LogError("[ReplanVLM] No valid message block in response.");
            yield break;
        }

        string outputText = null;
        foreach (var contentItem in messageBlock.content)
        {
            if (contentItem.type == "output_text")
            {
                outputText = contentItem.text;
                break;
            }
        }

        if (string.IsNullOrEmpty(outputText))
        {
            Debug.LogError("[ReplanVLM] No output_text found!");
            yield break;
        }

        output = outputText.Trim();
        Debug.Log("[ReplanVLM] Output:\n" + output);
    }


    // IEnumerator CallOpenAIAPI(string prompt)
    // {
    //     string APIKey = main.getOpenAIAPIKey();
    //     string APIurl = main.getOpenAIAPIURL(); 

    //     // // Convert image to PNG and then Base64
    //     // byte[] imageBytes = image.EncodeToPNG();
    //     // string base64Image = System.Convert.ToBase64String(imageBytes);

    //     // Escape prompt string for JSON
    //     string escapedPrompt = prompt.Replace("\\", "\\\\")
    //                                  .Replace("\"", "\\\"")
    //                                  .Replace("\n", "\\n")
    //                                  .Replace("\r", "\\r");

    //     string jsonRequest = $@"{{
    //         ""model"": ""o3"",
    //         ""messages"": [
    //             {{
    //                 ""role"": ""system"",
    //                 ""content"": ""You are a VLM that detects execution errors.""
    //             }},
    //             {{
    //                 ""role"": ""user"",
    //                 ""content"": [
    //                         {{ ""type"": ""text"", ""text"": ""{escapedPrompt}"" }}
    //                     ]
    //             }}
    //         ]
    //     }}";

    //     UnityWebRequest request = new UnityWebRequest(APIurl, "POST");
    //     byte[] bodyRaw = System.Text.Encoding.UTF8.GetBytes(jsonRequest);
    //     request.uploadHandler = new UploadHandlerRaw(bodyRaw);
    //     request.downloadHandler = new DownloadHandlerBuffer();

    //     request.SetRequestHeader("Content-Type", "application/json");
    //     request.SetRequestHeader("Authorization", $"Bearer {APIKey}");

    //     Debug.Log("[OuterBot] Sending OpenAI API Request...");
    //     yield return request.SendWebRequest();
    //     Debug.Log("[OuterBot] Received API Response.");

    //     if (request.result != UnityWebRequest.Result.Success)
    //     {
    //         Debug.LogError($"[OuterBot] API Request Failed: {request.error}\n{request.downloadHandler.text}");
    //     }
    //     else
    //     {
    //         string jsonResponse = request.downloadHandler.text;

    //         OpenAIResponse response = JsonUtility.FromJson<OpenAIResponse>(jsonResponse);

    //         Debug.Log("[OuterBot] Raw API response:\n" + jsonResponse);

    //         if (response.choices != null && response.choices.Length > 0)
    //         {
    //             output = response.choices[0].message.content.Trim();
    //             Debug.Log("[OuterBot] OpenAI Output:\n" + output);

    //             // Extract only the block between your specified flags
    //             string error_result = main.ExtractBetweenFlags(output, "```start_error_type", "```end_error_type");

    //             Debug.Log("EXTRACTED Outer Bot Error Block:\n" + error_result);

    //             // Extract the Error type directly (RECOVERABLE / NON-RECOVERABLE)
    //             int index = error_result.IndexOf("Error :");

    //             if (index != -1)
    //             {
    //                 feedback = error_result.Substring(index + "Error :".Length).Trim();
    //                 Debug.Log("OUTERBOT VERDICT = " + feedback);
    //             }
    //             else
    //             {
    //                 Debug.LogWarning("[OuterBot] Error type string not found in output block.");
    //             }
    //         }
    //         else
    //         {
    //             Debug.LogError("[OuterBot] OpenAI API returned empty choices or malformed response.");
    //         }
    //     }
    // }


    [Serializable]
    public class ResponsesAPIResponse
    {
        public string id;
        public OutputItem[] output;
    }

    [Serializable]
    public class OutputItem
    {
        public string type;           // "reasoning" or "message"
        public ContentItem[] content; // only present when type=="message"
    }

    [Serializable]
    public class ContentItem
    {
        public string type;  // "output_text"
        public string text;  // the assistant’s actual response
    }


    // // Response wrapper for JsonUtility
    // [System.Serializable]
    // private class OpenAIResponse
    // {
    //     public Choice[] choices;
    // }

    // [System.Serializable]
    // private class Choice
    // {
    //     public Message message;
    // }

    // [System.Serializable]
    // private class Message
    // {
    //     public string role;
    //     public string content;
    // }
}
