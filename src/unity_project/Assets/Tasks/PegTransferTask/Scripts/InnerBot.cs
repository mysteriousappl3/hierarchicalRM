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

    public string output;
    public string promptTemplateState;
    public string promptTemplate;

    public string verdict = "";


    void Start()
    {
        output = "";
        // Prompt for Inner Bot for State
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

        // Prompt for Inner Bot for Plan
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
        string userInstruction = main.userInstruction;

        if (userInstruction == "")
        {
           Debug.Log("[InnerBot] -- Empty user instruction!");
           yield break;
        }

        string currentSceneDesc = sceneDescriptor.output;

        if (currentSceneDesc == "")
        {
           Debug.Log("[InnerBot] -- Please generate current state scene description");
           yield break;
        }

        string stateDescription = stateDescriptor.output;

        if (stateDescription == "")
        {
           Debug.Log("[InnerBot] -- Please generate state description");
           yield break;
        }

        string h1Actions = "";
        string h2Actions = "";
        string decisionBotOutput = "";

        if (!isStateDesc)
        {
            h1Actions = h1ActionGenerator.output;
            if (h1Actions == "")
            {
                Debug.Log("[InnerBot] -- H1 Actions empty!");
                yield break;
            }

            h2Actions = h2ActionGenerator.output;
            if (h2Actions == "")
            {
                Debug.Log("[InnerBot] -- H2 Actions empty!");
                yield break;
            }

            decisionBotOutput = decisionBot.output;
            if (decisionBotOutput == "")
            {
                Debug.Log("[InnerBot] -- Please generate a plan by calling Decision Bot!");
                yield break;
            }
        }

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

        // Escape prompt string for JSON
        string escapedPrompt = prompt.Replace("\\", "\\\\")
                                            .Replace("\"", "\\\"")
                                            .Replace("\n", "\\n")
                                            .Replace("\r", "\\r");

        // Build JSON request body
        string jsonRequest = $@"{{
            ""model"": ""gpt-5.1"",
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
            ""reasoning_effort"": ""low""
        }}";

        UnityWebRequest request = new UnityWebRequest(APIurl, "POST");
        byte[] bodyRaw = System.Text.Encoding.UTF8.GetBytes(jsonRequest);
        request.uploadHandler = new UploadHandlerRaw(bodyRaw);
        request.downloadHandler = new DownloadHandlerBuffer();

        request.SetRequestHeader("Content-Type", "application/json");
        request.SetRequestHeader("Authorization", $"Bearer {APIKey}");

        Debug.Log("[InnerBot] Sending request...");
        yield return request.SendWebRequest();
        Debug.Log("[InnerBot] Response received.");

        if (request.result != UnityWebRequest.Result.Success)
        {
            Debug.LogError($"[InnerBot] API Request Failed: {request.error}\n{request.downloadHandler.text}");
        }
        else
        {
            string jsonResponse = request.downloadHandler.text;

            OpenAIResponse response = JsonUtility.FromJson<OpenAIResponse>(jsonResponse);

            if (response.choices != null && response.choices.Length > 0)
            {
                output = response.choices[0].message.content.Trim();
                output = main.ExtractBetweenFlags(output, "```start_result", "```end_result");
                main.innerbot_feedback = output;
                Debug.Log("[InnerBot] Extracted verdict: " + output);

                // Extract substring after "RESULT:" string
                int index = output.IndexOf("RESULT:");
                if (index != -1)
                {
                    string resultLine = output.Substring(index + "RESULT:".Length).Trim();
                    string[] lines = resultLine.Split(new[] { '\n', '\r' }, StringSplitOptions.RemoveEmptyEntries);
                    verdict = lines[0].Trim();
                    Debug.Log("[InnerBot] Verdict: " + verdict);
                }
                else
                {
                    Debug.LogWarning("[InnerBot] RESULT field not found in output.");
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
