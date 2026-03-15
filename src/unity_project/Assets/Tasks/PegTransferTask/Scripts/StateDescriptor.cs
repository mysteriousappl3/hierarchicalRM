using UnityEngine;
using UnityEngine.Networking;
using System.Collections;
using System;
using System.IO;

public class StateDescriptor : MonoBehaviour
{
    public SceneDescriptor sceneDescriptor;

    public Main main;

    public string promptTemplate;
    public string predicates_description;
    public string output;

    void Start()
    {
        output = "";

        promptTemplate = @"
            Using the given JSON scene description and user instruction,
            create a dictionary called ""goal_spatial_relations"". Also don't forget to generate another dictionary
            that is called ""constraint_spatial_relations"" so that it contains any restrictions/constraints on action performed by the robot at any time given in the user instruction.
            Both ""goal_spatial_relations"" and ""constraint_spatial_relations"" should follow the format of spatial_relations.
            Note that spatial_relations denotes the list of relationships between objects. Use only the following objects to describe these relations. [A, B] means A AND B and you may use (A OR B) and NOT A to indicate disjunction and negation. Make sure your predicate only contains object names as parameters.
            {predicates_description}
            If there are no constraints that the robot must follow in every action, it should be empty.
            Please take note of the following:
            1. The response should be a Python dictionary only, without any explanatory text (e.g., Do not include a sentence like ""here is the environment"").
            
            VLM output format:
            {
                ""goal_spatial_relations"": {
                    ""<object_one>"": [""predicate_one(<object_three>)""],
                    ""<object_two>"": [...],
                    ...
                },
                ""constraint_spatial_relations"": {
                    ""<object_one>"": [
                        ""NOT(predicate_two(<another_object>))"",
                        ""NOT(predicate_three(<another_object_2>))""
                    ],
                    ""<object_two>"": [
                        ""predicate_five(<another_object_3>)""
                    ],
                    ...
                }
            }


            Also, a previous response of this VLM and a feedback on either the state descriptor dictionary or a generated plan are provided OPTIONALLY.
            If the feedback is on the state descriptor JSON OR you think your previous response do not interpret the user instruction accurately,
            generate a new state descriptor JSON. Otherwise, JUST RETURN the previous state descriptor JSON without any changes.
            If the feedback is on the generated plan and you don't think it has anything to do with the goal state or constrinst you defined, you can ignore it and just return the previous state descriptor JSON.
            If the previous state descriptor JSON is not provided, you can generate a new state descriptor JSON.

            Now, solve the following task:
            User Instruction: {user_instruction}
            Scene Description JSON: {scene_description}
            Previous state description JSON: {state_description}
            Previous feedback: {previous_feedback}

            Make sure to wrap the entire JSON definition for both dictionary within a ```start_flag and ```end_flag for parsing purposes.
            ";

        predicates_description = "Here are the predicates to be used: [in(), above()].\nFor example, ‘in(<obj_1>)’ indicates that an object is in obj_1 and ‘above(<obj_2>)’ means an object is DIRECTLY above obj_2 and there are no objects between them.";
    }

    public IEnumerator generateStateDescription()
    {
        string userInstruction = main.userInstruction;

        if (userInstruction == "")
        {
            Debug.Log("[StateDescriptor] -- Please ensure a non-empty user instruction is provided");
            yield break;
        }

        string sceneDescriptionJSON = sceneDescriptor.output;

        if (sceneDescriptionJSON == "")
        {
            Debug.Log("[StateDescriptor] -- Please ensure sceneDescriptor is called first");
            yield break;
        }

        string state_description = main.stateDescription;   // optional: empty on first call
        string previous_feedback = main.innerbot_feedback;  // optional: empty on first call

        string prompt = promptTemplate
                    .Replace("{scene_description}", sceneDescriptionJSON)
                    .Replace("{user_instruction}", userInstruction)
                    .Replace("{predicates_description}", predicates_description)
                    .Replace("{state_description}", state_description)
                    .Replace("{previous_feedback}", previous_feedback);

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
            ""model"": ""o4-mini"",
            ""messages"": [
                {{
                    ""role"": ""system"",
                    ""content"": ""As a state representation VLM, you will be given user instructions on a task.""
                }},
                {{
                    ""role"": ""user"",
                    ""content"": ""{escapedPrompt}""
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

        Debug.Log("[StateDescriptor] Sending OpenAI API Request...");
        yield return request.SendWebRequest();
        Debug.Log("[StateDescriptor] Received API Response.");

        if (request.result != UnityWebRequest.Result.Success)
        {
            Debug.LogError($"[StateDescriptor] API Request Failed: {request.error}\n{request.downloadHandler.text}");
        }
        else
        {
            string jsonResponse = request.downloadHandler.text;

            OpenAIResponse response = JsonUtility.FromJson<OpenAIResponse>(jsonResponse);
            Debug.Log("[StateDescriptor] Raw API response:\n" + jsonResponse);

            if (response.choices != null && response.choices.Length > 0)
            {
                output = response.choices[0].message.content.Trim();
                Debug.Log("[StateDescriptor] OpenAI Output:\n" + output);
                output = main.ExtractBetweenFlags(output);
                Debug.Log("EXTRACTED DATA ");
                Debug.Log(output);

                // Store the reference to initial state descriptor to extract env_constraints from for InnerBot usage.
                main.initialStateDesc = output;

                // Extract env_constraints
                string extracted_env_constraint = main.ExtractConstraintSpatialRelations(output);
                Debug.Log("Extracted constraint_spatial_relations JSON:\n" + extracted_env_constraint);
                main.envConstraint = extracted_env_constraint;
                main.stateDescription = output;
            }
            else
            {
                Debug.LogError("[StateDescriptor] OpenAI API returned empty choices or malformed response.");
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
