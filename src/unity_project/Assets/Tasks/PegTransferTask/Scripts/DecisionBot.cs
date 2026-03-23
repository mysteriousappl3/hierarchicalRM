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

    public string lastResponseId = null;

    void Start()
    {
        output = "";

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

            CRITICAL: When calling functions, you MUST substitute the actual peg names from the scene description (e.g., ""green_peg"", ""red_peg"", ""blue_peg"") as arguments.
            Do NOT pass abstract parameter placeholder names from the function signatures.
            Every argument in every function call must be a concrete object name that exists in the scene.

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

            Wrap the sequence of all function calls in ```start_all_functions and ```end_all_functions flags.

            Wrap each of the subtasks in ```start_subtask_{num} and ```end_subtask_{num} flags.

            Wrap each of the subtasks goal states in ```start_subtask_goalstate_{num} and ```end_subtask_goalstate_{num} flags.

            Wrap each of the subtasks function calls in ```start_subtask_funcs_{num} and ```end_subtask_funcs_{num} flags.
            ";
    }

    public IEnumerator generateDecisionBotPlan()
    {
        string userInstruction = main.userInstruction;

        if (userInstruction == "")
        {
            Debug.Log("[DecisionBot] -- Please ensure a non-empty user instruction is provided");
            yield break;
        }

        string sceneDescriptionJSON = sceneDescriptor.output;

        if (sceneDescriptionJSON == "")
        {
            Debug.Log("[DecisionBot] -- Please ensure scene description is generated prior to generating plan");
            yield break;
        }

        string stateDescriptionJSON = stateDescriptor.output;

        if (stateDescriptionJSON == "")
        {
            Debug.Log("[DecisionBot] -- Please ensure state description is generated prior to generating plan");
            yield break;
        }

        string h1Actions = h1ActionGenerator.output;

        if (h1Actions == "")
        {
            Debug.Log("[DecisionBot] -- Please ensure H1 actions are generated prior to generating plan");
            yield break;
        }

        string h2Actions = h2ActionGenerator.output;

        if (h2Actions == "")
        {
            Debug.Log("[DecisionBot] -- Please ensure H2 actions are generated prior to generating plan");
            yield break;
        }

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
        
        string prompt = promptTemplate
                    .Replace("{h1_actions}", h1Actions)
                    .Replace("{h2_actions}", h2Actions)
                    .Replace("{outer_bot_feedback}", outerBotFeedback)
                    .Replace("{inner_bot_feedback}", innerBotFeedback)
                    .Replace("{user_instruction}", userInstruction)
                    .Replace("{scene_description}", sceneDescriptionJSON)
                    .Replace("{state_description}", stateDescriptionJSON);

        yield return StartCoroutine(CallOpenAIAPI(prompt));
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
            ""model"": ""gpt-5.1"",
            ""reasoning"": {{ ""effort"": ""low"" }},
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

        Debug.Log("[DecisionBot] Sending request...");
        yield return request.SendWebRequest();
        Debug.Log("[DecisionBot] Response received.");

        if (request.result != UnityWebRequest.Result.Success)
        {
            Debug.LogError($"[DecisionBot] API Request Failed: {request.error}\n{request.downloadHandler.text}");
            yield break;
        }

        // 5) Deserialize into the new Responses API schema
        string jsonResponse = request.downloadHandler.text;
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

        // 10) Log parsed plan
        Debug.Log("[DecisionBot] Subtask descriptions:\n" + string.Join("\n", main.subtaskDescriptions));
        for (int i = 0; i < main.subtaskFunctions.Count; i++)
            Debug.Log($"[DecisionBot] Subtask {i + 1} functions: {string.Join(", ", main.subtaskFunctions[i])}");
        Debug.Log("[DecisionBot] All function calls: " + string.Join(", ", main.allFunctions));
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

}
