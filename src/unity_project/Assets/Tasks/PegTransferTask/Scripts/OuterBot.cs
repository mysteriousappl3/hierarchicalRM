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

    public string lastResponseId = null;

    void Start()
    {
        output = "";
        feedback = "";

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

            Wrap your answer exactly as below including the quotation mark:

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

    }

    public IEnumerator verifyTaskCompletion(string subtaskNL, string subtaskGoalState, string finalGoalState)
    {
        if (subtaskNL == "")
        {
            Debug.Log("[OuterBot] -- Subtask natural language description is empty!");
            yield break;
        }

        if (subtaskGoalState == "")
        {
            Debug.Log("[OuterBot] -- Subtask goal state is empty!");
            yield break;
        }

        if (finalGoalState == "")
        {
            Debug.Log("[OuterBot] -- Final goal state is empty!");
            yield break;
        }

        string currentSceneDesc = sceneDescriptor.output;

        if (currentSceneDesc == "")
        {
            Debug.Log("[OuterBot] -- Error generating scene description for the image");
            yield break;
        }

        string env_constraint = main.envConstraint;

        if (env_constraint == "")
        {
            Debug.Log("[OuterBot] -- Environment constraint is empty!");
            yield break;
        }

        if (main.prevState == "")
        {
            Debug.Log("[OuterBot] -- Previous state is empty!");
            yield break;
        }

        string prompt = promptTemplate
                    .Replace("{env_constraint}", env_constraint)
                    .Replace("{subtask_nl}", subtaskNL)
                    .Replace("{prev_state}", main.prevState)
                    .Replace("{curr_state}", currentSceneDesc)
                    .Replace("{subtask_goal_state}", subtaskGoalState)
                    .Replace("{final_goal_state}", finalGoalState)
                    ;

        yield return StartCoroutine(CallOpenAIAPI(prompt));
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
}
