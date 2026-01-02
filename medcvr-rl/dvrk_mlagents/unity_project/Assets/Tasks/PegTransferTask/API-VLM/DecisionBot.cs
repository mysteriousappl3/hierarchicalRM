using System;
using System.Collections;
using System.Collections.Generic;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;
using System.Linq;
using System.IO;

public class DecisionBot : MonoBehaviour
{
    public Main main;
    public SceneDescriptor sceneDescriptor;
    public StateDescriptor stateDescriptor;
    public H1ActionGenerator h1ActionGenerator;
    public H2ActionGenerator h2ActionGenerator;
    public OuterBot outerBot;
    public InnerBot innerBot;

    public string output;
    public string promptTemplate;
    public string replanVlmPrompt;

    public string lastResponseId = null;

    void Start()
    {
        output = "";

        // Note: If you use a different scene, then the Role play: section will change to include proper ordering of the pegs unless we change our design to use VLM to use colors.
        // Then, we can have a variable in that scene to map the color to the peg number to avoid frequent changes to the prompts. This seems like the better idea to go with and makes
        // our solution scalable and easier to debug and work with.

        promptTemplate = @"
            This is the task that we want to perform: (Look carefully at the user instruction and constraints)
            {user_instruction}

            Divide the task into subtasks and generate a goal state dictionary for each subtask, then use the H2 and H1 level action function(s) 
            to plan this task. Give the result as a sequence of function calls.
            It is important that in your subtasks, you mention all objects explicity and not in any vague terminology.
            Also, try your best to include more than one function call in each subtask, if possible, to make the plan more efficient, unless the entire plan has only one call.
            However, try to come up with a plan that uses fewest number of function calls to achieve the goal state. 
            If after two to three rounds of planning, you are not able to generate a plan that satisfies goal state and contraints, you MUST generate a plan regardless of that.
            Hint: If you don't know how to solve the task, you can reduce it to a problem you know and try to solve that problem but remember your ultimate goal is to solve the given task.

            Example: Output should be like this:

            For each subtask, print:
            - Subtask's description
            - Subtask's goal state dictionary
            - Call(s) to complete the subtask

            Then, finally, give the sequence of all H2/H1 function calls together like this:

            FunctionA()
            FunctionB()
            .
            .
            .

            Do not output any parameter in the format ""<object_black>"" or similar. Strictly refer to them of the format of ""object_black"".

            You MUST follow the above output format and do not put any additional text or explanation in the output.

            In the state description, the state objects are ordered bottom-up, left-to-right order.  

            Please remember when generating goal state JSON for each subtask, you match the structure with all objects in scene as down in scene JSON representation shown.

            Assume that the given scene and state description JSON are for the current state of the scene and any planning must happen relative to this given input description.

            Here is the scene description JSON that shows the objects in the scene:

            {scene_description}

            Here is the state description JSON that shows the constraints on objects' relative positions:

            {state_description}

            Here are the H1 level functions:

            {h1_actions}

            Here are the H2 level functions:

            {h2_actions}

            Here is the feedback given by the InnerBot Verifier from previous plan generation:

            {inner_bot_feedback}

            Here is the feedback given by the OuterBot Verifier from previous plan generation:

            {outer_bot_feedback}


            STRICT OUTPUT RULES (MUST FOLLOW EXACTLY):

            1. The subtask function calls must use explicit object identifiers (color + object type), for example ""green_peg"".
            Never output placeholders or parameter names (e.g., ""source_peg"", ""destination_peg"", ""fromPeg"").
            Every argument in every function call must match the same concrete object name consistently throughout the entire plan.

            2. Wrap the sequence of all function calls in ```start_all_functions and ```end_all_functions flags.

            3. Wrap each of the subtasks in ```start_subtask_{num} and ```end_subtask_{num} flags.

            4. Wrap each of the subtasks goal states in ```start_subtask_goalstate_{num} and ```end_subtask_goalstate_{num} flags.

            5. Wrap each of the subtasks function calls in ```start_subtask_funcs_{num} and ```end_subtask_funcs_{num} flags.

            OUTPUT TEMPLATE (FOLLOW EXACTLY, NO EXTRA TEXT):

            <<START_SUBTASK_1>>
            Subtask's description: ...
            <<START_SUBTASK_GOALSTATE_1>>
            { ...valid JSON... }
            <<END_SUBTASK_GOALSTATE_1>>
            <<START_SUBTASK_FUNCS_1>>
            FuncA(arg1, arg2)
            FuncB(arg1, arg2)
            <<END_SUBTASK_FUNCS_1>>
            <<END_SUBTASK_1>>

            <<START_SUBTASK_2>>
            ...
            <<END_SUBTASK_2>>

            <<START_ALL_FUNCTIONS>>
            FuncA(...)
            FuncB(...)
            ...
            <<END_ALL_FUNCTIONS>>
            ";

        replanVlmPrompt = @"
            You are a task planning robot responsible for task planning and automatically generate code which outlines the execution plan.
            Error messages from Inner Bot or Outer Bot feedback may also not exist.

            Here's the instruction:
            {user_instruction}

            Code repository:
            MoveCoroutine(reachable_object): Move robot arm above stationary input object. Objects not reachable cannot be passed as input.
            GrabCoroutine(): Pick up top 'GRABBABLE' object below current position. Objects not GRABBABLE cannot be passed as input.
            DropCoroutine(): Drop picked up object at current position.
            PushCoroutine(final_dest): Push object at current position to specified position.
            RollCoroutine(direction): Roll object at current position in specified direction.
            CutCoroutine(): Cut top object below current position.

            First, deduce the task step by step, and then automatically generate code based on the information in the task library. Here is an example:
            1. Grab the apple first
            2. Give it to me
            code:
            grasp(apple)
            giveMe(apple)
        ";
    }

    public IEnumerator generateDecisionBotPlan()
    {
        string userInstruction = main.userInstruction;

        //if (userInstruction == "")
        //{
        //    Debug.Log("[DecisionBot] -- Please ensure a non-empty user instruction is provided");
        //    yield break;
        //}

        //string h1Actions = h1ActionGenerator.output;

        //if (h1Actions == "")
        //{
        //    Debug.Log("[DecisionBot] -- Please ensure H1 actions are generated prior to generating plan");
        //    yield break;
        //}

        //string h2Actions = h2ActionGenerator.output;

        //if (h2Actions == "")
        //{
        //    Debug.Log("[DecisionBot] -- Please ensure H2 actions are generated prior to generating plan");
        //    yield break;
        //}

        //string sceneDescription = sceneDescriptor.output;

        //if (sceneDescription == "")
        //{
        //    Debug.Log("[DecisonBot] -- Please ensure scene description is generated prior to generating plan");
        //    yield break;
        //}

        //string stateDescription = stateDescriptor.output;

        //if (stateDescription == "")
        //{
        //    Debug.Log("[DecisonBot] -- Please ensure scene description is generated prior to generating plan");
        //    yield break;
        //}


        // string stateDescriptionJSON = @"
        //     {
        //         ""goal_spatial_relations"": {
        //             ""ring_purple"": [""in(peg_red)""],
        //             ""ring_white"": [""in(peg_red)"", ""above(ring_purple)""],
        //             ""ring_yellow"": [""in(peg_red)"", ""above(ring_white)""]  
        //         },
        //         ""constraint_spatial_relations"": {
        //             ""ring_purple"": [
        //                 ""NOT(above(ring_purple, ring_white))"",
        //                 ""NOT(above(ring_purple, ring_yellow))""
        //             ],
        //             ""ring_white"": [
        //                 ""NOT(above(ring_white, ring_yellow))""
        //             ],
        //             ""ring_yellow"": []
        //         }
        //     }";

        string stateDescriptionJSON = stateDescriptor.output;

        // string sceneDescriptionJSON = @"
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

        string sceneDescriptionJSON = sceneDescriptor.output;

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

        string outerBotFeedback = outerBot.output;

        if (outerBotFeedback == "")
        {
            outerBotFeedback = "N/A";
        }

        string innerBotFeedback = innerBot.output;

        if (innerBotFeedback == "")
        {
            innerBotFeedback = "N/A";
        }

        Debug.Log("[DECISION BOT] Scene Desc -- " + sceneDescriptionJSON);
        Debug.Log("[DECISION BOT] User Instruction -- " + userInstruction);
        Debug.Log("[DECISION BOT] State Desc -- " + stateDescriptionJSON);
        Debug.Log("[DECISION BOT] Inner feedback -- " + innerBotFeedback);
        Debug.Log("[DECISION BOT] Outer feedback -- " + outerBotFeedback);
        
        string prompt = promptTemplate
                    .Replace("{h1_actions}", h1Actions)
                    .Replace("{h2_actions}", h2Actions)
                    .Replace("{outer_bot_feedback}", outerBotFeedback)
                    .Replace("{inner_bot_feedback}", innerBotFeedback)
                    .Replace("{user_instruction}", userInstruction)
                    .Replace("{scene_description}", sceneDescriptionJSON)
                    .Replace("{state_description}", stateDescriptionJSON);

        // TODO: OpenAI/Deepseek API call to pass 'prompt' sceneDescription, stateDescription, H1 actions, H2 actions and 'userInstruction' to the model
        // to generate output and save in 'output' variable
        //StartCoroutine(CallDeepSeekAPI(prompt));

        // yield return StartCoroutine(CallOpenAIAPI(prompt));

        // replanVLM: Use the same image path logic as StateDescriptor
        string imagePath = Path.Combine(Application.dataPath, $"Tasks/PegTransferTask/Task_Images/SceneImage_{main.imageCounter}.png");
        // yield return StartCoroutine(CallReplanVlmApi(imagePath));
        // yield return StartCoroutine(CallOpenAIAPI(prompt));

        yield return StartCoroutine(CallGeminiAPI(prompt));
    }

    IEnumerator CallOpenAIAPI(string prompt)
    {
        string APIKey = main.getOpenAIAPIKey();
        string APIurl = main.getOpenAIReasoningURL(); // should point to /v1/responses

        // 1) Prepare and escape your system & user texts
        string systemText = "You are planner VLM responsible for planning for the given user instruction into several subtasks.";
        string escapedSystem = systemText
            .Replace("\\", "\\\\")
            .Replace("\"", "\\\"");
        string escapedUser = prompt
            .Replace("\\", "\\\\")
            .Replace("\"", "\\\"")
            .Replace("\n", "\\n")
            .Replace("\r", "\\r");

        // 2) Conditionally include previous_response_id only when non-null
        string prevIdPart = string.IsNullOrEmpty(lastResponseId)
            ? ""
            : $",\n    \"previous_response_id\": \"{lastResponseId}\"";

        // 3) Build the full JSON body manually
        string jsonRequest = $@"{{
            ""model"": ""o4-mini"",
            ""reasoning"": {{ ""effort"": ""high"" }},
            ""input"": [
                {{
                    ""role"": ""system"",
                    ""content"": ""{escapedSystem}""
                }},
                {{
                    ""role"": ""user"",
                    ""content"": ""{escapedUser}""
                }}
            ]{prevIdPart}
        }}";

        // 4) Send the HTTP POST
        UnityWebRequest request = new UnityWebRequest(APIurl, "POST");
        byte[] bodyRaw = Encoding.UTF8.GetBytes(jsonRequest);
        request.uploadHandler   = new UploadHandlerRaw(bodyRaw);
        request.downloadHandler = new DownloadHandlerBuffer();
        request.SetRequestHeader("Content-Type", "application/json");
        request.SetRequestHeader("Authorization", $"Bearer {APIKey}");

        Debug.Log("[DecisionBot] Sending OpenAI Responses API Request...");
        yield return request.SendWebRequest();
        Debug.Log("[DecisionBot] Received API Response.");

        if (request.result != UnityWebRequest.Result.Success)
        {
            Debug.LogError($"[DecisionBot] API Request Failed: {request.error}\n{request.downloadHandler.text}");
            yield break;
        }

        // 5) Deserialize into the new Responses API schema
        string jsonResponse = request.downloadHandler.text;
        Debug.Log("[DecisionBot] Raw API response:\n" + jsonResponse);
        var response = JsonUtility.FromJson<ResponsesAPIResponse>(jsonResponse);

        // 6) Save the response ID for next call
        lastResponseId = response.id;

        // 7) Extract the assistant’s content from output[] where type=="message"
        var messageBlock = response.output
            .FirstOrDefault(o => o.type == "message" && o.content != null);
        if (messageBlock == null)
        {
            Debug.LogError("[DecisionBot] No message block found in response.output!");
            yield break;
        }
        var outputText = messageBlock.content
            .FirstOrDefault(c => c.type == "output_text")?.text;
        if (outputText == null)
        {
            Debug.LogError("[DecisionBot] No output_text found in messageBlock.content!");
            yield break;
        }
        string content = outputText.Trim();
        output = content;
        Debug.Log("[DecisionBot] OpenAI Output:\n" + content);

        // 8) Run your existing parsing logic on that content
        main.ParseDecisionBotOutput(
            content,
            out main.subtaskDescriptions,
            out main.subtaskFunctions,
            out main.subtaskGoalstates,
            out main.allFunctions
        );

        // 9) Expand to H1-only and reset the index as before
        main.subtaskFunctions = main.ExpandToH1Only(main.subtaskFunctions);
        main.index = 0;

        // 10) Your debug logs remain unchanged
        Debug.Log("EXTRACTED Decision Bot DATA ");
        Debug.Log(string.Join("\n", main.subtaskDescriptions));
        for (int i = 0; i < main.subtaskFunctions.Count; i++)
            Debug.Log($"Functions for Subtask {i + 1}: {string.Join(", ", main.subtaskFunctions[i])}");
        Debug.Log(string.Join("\n", main.subtaskGoalstates));
        Debug.Log($"All function calls: {string.Join(", ", main.allFunctions)}");
    }

IEnumerator CallGeminiAPI(string prompt)
{
    string APIKey = main.getGeminiAPIKey();
    string APIurl = main.getGeminiAPIUrl();

    // 1) Prepare and escape your system & user texts
    string systemText = "You are planner VLM responsible for planning for the given user instruction into several subtasks.";
    string escapedSystem = systemText
        .Replace("\\", "\\\\")
        .Replace("\"", "\\\"");
    string escapedUser = prompt
        .Replace("\\", "\\\\")
        .Replace("\"", "\\\"")
        .Replace("\n", "\\n")
        .Replace("\r", "\\r");

    // 2) Conditionally include previous_response_id only when non-null (Gemini does not support this field natively)
    string prevIdPart = string.IsNullOrEmpty(lastResponseId)
        ? ""
        : $",\n    \"previous_response_id\": \"{lastResponseId}\"";

    // 3) Build the full JSON body manually (Gemini generateContent schema)
    // NOTE: prevIdPart is intentionally not injected into the Gemini JSON because it would cause a schema error.
    string jsonRequest = $@"{{
        ""systemInstruction"": {{
            ""parts"": [
                {{ ""text"": ""{escapedSystem}"" }}
            ]
        }},
        ""contents"": [
            {{
                ""role"": ""user"",
                ""parts"": [
                    {{ ""text"": ""{escapedUser}"" }}
                ]
            }}
        ],
        ""generationConfig"": {{
                ""temperature"": 0.0,
                ""thinkingConfig"": {{
                    ""thinkingLevel"": ""low""
                }}
            }}
    }}";

    // 4) Send the HTTP POST
    UnityWebRequest request = new UnityWebRequest(APIurl, "POST");
    byte[] bodyRaw = Encoding.UTF8.GetBytes(jsonRequest);
    request.uploadHandler = new UploadHandlerRaw(bodyRaw);
    request.downloadHandler = new DownloadHandlerBuffer();
    request.SetRequestHeader("Content-Type", "application/json");

    // Gemini API key header (works for Generative Language API style endpoints)
    request.SetRequestHeader("x-goog-api-key", APIKey);

    Debug.Log("[DecisionBot] Sending Gemini API Request...");
    yield return request.SendWebRequest();
    Debug.Log("[DecisionBot] Received API Response.");

    if (request.result != UnityWebRequest.Result.Success)
    {
        Debug.LogError($"[DecisionBot] API Request Failed: {request.error}\n{request.downloadHandler.text}");
        yield break;
    }

    // 5) Deserialize into the Gemini schema
    string jsonResponse = request.downloadHandler.text;
    Debug.Log("[DecisionBot] Raw API response:\n" + jsonResponse);
    var response = JsonUtility.FromJson<GeminiAPIResponse>(jsonResponse);

    // 6) Save the response ID for next call (Gemini responses typically don't return a stable response id)
    // Keep the existing variable updated without changing downstream logic.
    lastResponseId = response != null ? response.GetPseudoId() : "";

    // 7) Extract the assistant’s content from candidates[0].content.parts[0].text
    if (response == null || response.candidates == null || response.candidates.Length == 0)
    {
        Debug.LogError("[DecisionBot] No candidates found in Gemini response!");
        yield break;
    }
    var cand = response.candidates[0];
    if (cand.content == null || cand.content.parts == null || cand.content.parts.Length == 0)
    {
        Debug.LogError("[DecisionBot] No content parts found in Gemini candidate!");
        yield break;
    }
    string outputText = cand.content.parts[0].text;
    if (string.IsNullOrEmpty(outputText))
    {
        Debug.LogError("[DecisionBot] Empty text in Gemini response!");
        yield break;
    }

    string content = outputText.Trim();
    output = content;
    Debug.Log("[DecisionBot] Gemini Output:\n" + content);

    // 8) Run your existing parsing logic on that content
    main.ParseDecisionBotOutputGemini(
        content,
        out main.subtaskDescriptions,
        out main.subtaskFunctions,
        out main.subtaskGoalstates,
        out main.allFunctions
    );

    // 9) Expand to H1-only and reset the index as before
    main.subtaskFunctions = main.ExpandToH1Only(main.subtaskFunctions);
    main.index = 0;

    // 10) Your debug logs remain unchanged
    Debug.Log("EXTRACTED Decision Bot DATA ");
    Debug.Log(string.Join("\n", main.subtaskDescriptions));
    for (int i = 0; i < main.subtaskFunctions.Count; i++)
        Debug.Log($"Functions for Subtask {i + 1}: {string.Join(", ", main.subtaskFunctions[i])}");
    Debug.Log(string.Join("\n", main.subtaskGoalstates));
    Debug.Log($"All function calls: {string.Join(", ", main.allFunctions)}");
}

[Serializable]
public class GeminiAPIResponse
{
    public GeminiCandidate[] candidates;

    // No official stable "response id" in many Gemini responses; keep this lightweight.
    public string GetPseudoId()
    {
        // Anything deterministic-ish is fine; downstream logic only expects a string.
        if (candidates != null && candidates.Length > 0 && candidates[0] != null && candidates[0].content != null
            && candidates[0].content.parts != null && candidates[0].content.parts.Length > 0)
        {
            string t = candidates[0].content.parts[0].text;
            if (!string.IsNullOrEmpty(t))
                return t.Length.ToString();
        }
        return "";
    }
}

[Serializable]
public class GeminiCandidate
{
    public GeminiContent content;
}

[Serializable]
public class GeminiContent
{
    public GeminiPart[] parts;
}

[Serializable]
public class GeminiPart
{
    public string text;
}





     public IEnumerator CallReplanVlmApi(string imagePath) {
            // 1. Load the image from file
            if (!File.Exists(imagePath))
            {
                Debug.LogError($"[ReplanVLM] Image file not found: {imagePath}");
                yield break;
            }

            byte[] imageData = File.ReadAllBytes(imagePath);
            string base64Image = Convert.ToBase64String(imageData);
            Debug.Log($"[ReplanVLM] Loaded image from {imagePath}");

            // 2. Prepare API credentials
            string APIKey = main.getOpenAIAPIKey();
            string APIurl = main.getOpenAIReasoningURL();

            // 3. Escape prompt
            replanVlmPrompt = replanVlmPrompt.Replace("{user_instruction}", main.userInstruction);
            string escapedPrompt = replanVlmPrompt
                .Replace("\\", "\\\\")
                .Replace("\"", "\\\"")
                .Replace("\n", "\\n")
                .Replace("\r", "\\r");

            // 4. Assemble request body with both text and image
            string jsonRequest = $@"{{
                ""model"": ""o4-mini"",
                ""reasoning"": {{ ""effort"": ""high"" }},
                ""input"": [
                    {{
                        ""role"": ""system"",
                        ""content"": ""You are a task planning robot responsible for task planning and automatically generate code which outlines the execution plan.""
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
                                ""image_url"": ""data:image/png;base64,{base64Image}""
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
            foreach (var item in response.output)
            {
                if (item.type == "message")
                {
                    messageBlock = item;
                    break;
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
        public string text;  // the assistant’s text
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

    //IEnumerator CallDeepSeekAPI(string promptContent)
    //{
    //    // Manual escape for JSON-compatibility
    //    string escapedPrompt = promptContent
    //        .Replace("\\", "\\\\")
    //        .Replace("\"", "\\\"")
    //        .Replace("\n", "\\n")
    //        .Replace("\r", "\\r");

    //    string jsonRequest = $@"{{
    //        ""model"": ""deepseek-reasoner"",
    //        ""messages"": [
    //            {{
    //                ""role"": ""user"",
    //                ""content"": ""{escapedPrompt}""
    //            }}
    //        ],
    //        ""temperature"": 0.1,
    //        ""max_tokens"": 1500
    //    }}";

    //    string apiUrl = main.getAPIURL();
    //    string apiKey = main.getAPIKey();

    //    UnityWebRequest request = new UnityWebRequest(apiUrl, "POST");
    //    byte[] bodyRaw = System.Text.Encoding.UTF8.GetBytes(jsonRequest);
    //    request.uploadHandler = new UploadHandlerRaw(bodyRaw);
    //    request.downloadHandler = new DownloadHandlerBuffer();
    //    request.SetRequestHeader("Content-Type", "application/json");
    //    request.SetRequestHeader("Authorization", "Bearer " + apiKey);

    //    yield return request.SendWebRequest();

    //    if (request.result != UnityWebRequest.Result.Success)
    //    {
    //        Debug.LogError($"API Request Failed: {request.error}\n{request.downloadHandler.text}");
    //    }
    //    else
    //    {
    //        string jsonResponse = request.downloadHandler.text;
    //        DeepSeekResponse response = JsonUtility.FromJson<DeepSeekResponse>(jsonResponse);

    //        if (response.choices != null && response.choices.Length > 0)
    //        {
    //            output = response.choices[0].message.content.Trim();
    //            Debug.Log("<color=cyan>--------- DeepSeek H2 Output ---------</color>\n" + output);
    //        }
    //        else
    //        {
    //            Debug.LogError("DeepSeek Reasoner returned empty result or malformed response.");
    //        }
    //    }
    //}

    //// Minimal response wrapper classes
    //[System.Serializable]
    //private class DeepSeekResponse
    //{
    //    public Choice[] choices;
    //}

    //[System.Serializable]
    //private class Choice
    //{
    //    public Message message;
    //}

    //[System.Serializable]
    //private class Message
    //{
    //    public string role;
    //    public string content;
    //}

}
