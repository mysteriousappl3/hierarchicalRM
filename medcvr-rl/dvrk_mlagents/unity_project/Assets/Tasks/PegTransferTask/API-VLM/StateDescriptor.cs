using UnityEngine;
using UnityEngine.Networking;
using System.Collections;
using System;
using System.IO;
using System.Text;

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

            STRICT OUTPUT RULE (MUST FOLLOW EXACTLY):
            It is very important to return ONLY the following format:

            ```start_flag
            <your response>
            ```end_flag
            ";

        // promptTemplate = @"
        //     Using the given JSON scene description and user instruction,
        //     create a dictionary called ""goal_spatial_relations"". 
        //     ""goal_spatial_relations"" should follow the format of spatial_relations.
        //     Note that spatial_relations denotes the list of relationships between objects. Use only the following objects to describe these relations. [A, B] means A AND B and you may use (A OR B) and NOT A to indicate disjunction and negation. Make sure your predicate only contains object names as parameters.
        //     {predicates_description}
        //     Please take note of the following:
        //     1. The response should be a Python dictionary only, without any explanatory text (e.g., Do not include a sentence like ""here is the environment"").
            
        //     VLM output format:
        //     {
        //         ""goal_spatial_relations"": {
        //             ""<object_one>"": [""predicate_one(<object_three>)""],
        //             ""<object_two>"": [...],
        //             ...
        //         }
        //     }


        //     Also, a previous response of this VLM and a feedback on either the state descriptor dictionary or a generated plan are provided OPTIONALLY.
        //     If the feedback is on the state descriptor JSON OR you think your previous response do not interpret the user instruction accurately,
        //     generate a new state descriptor JSON. Otherwise, JUST RETURN the previous state descriptor JSON without any changes.
        //     If the feedback is on the generated plan and you don't think it has anything to do with the goal state or constrinst you defined, you can ignore it and just return the previous state descriptor JSON.
        //     If the previous state descriptor JSON is not provided, you can generate a new state descriptor JSON.

        //     Now, solve the following task:
        //     User Instruction: {user_instruction}
        //     Scene Description JSON: {scene_description}
        //     Previous state description JSON: {state_description}
        //     Previous feedback: {previous_feedback}

        //     Make sure to wrap the entire JSON definition for both dictionary within a ```start_flag and ```end_flag for parsing purposes.
        //     ";

        predicates_description = "Here are the predicates to be used: [in(), above()].\nFor example, ‘in(<obj_1>)’ indicates that an object is in obj_1 and ‘above(<obj_2>)’ means an object is DIRECTLY above obj_2 and there are no objects between them.";
    }

    public IEnumerator generateStateDescription()
    {
        string userInstruction = main.userInstruction;

        //if (userInstruction == "")
        //{
        //    Debug.Log("[StateDescriptor] -- Please ensure a non-empty user instruction is provided");
        //    yield break;
        //}

        string sceneDescriptionJSON = sceneDescriptor.output;

        //sceneDescriptionJSON = @"
        //{
        //    ""objects"": [
        //        ""<peg_green>"",
        //        ""<hoop_yellow>"",
        //        ""<hoop_white>"",
        //        ""<hoop_purple>"",
        //        ""<peg_red>"",
        //        ""<peg_blue>""
        //    ],
        //    ""object_properties"": {
        //        ""<peg_green>"": [],
        //        ""<hoop_yellow>"": [""GRABBABLE""],
        //        ""<hoop_white>"": [""GRABBABLE""],
        //        ""<hoop_purple>"": [""GRABBABLE""],
        //        ""<peg_red>"": [],
        //        ""<peg_blue>"": []
        //    },
        //    ""spatial_relations"": {
        //        ""<peg_green>"": [],
        //        ""<hoop_yellow>"": [""in(<peg_green>)"", ""above(<hoop_white>)""],
        //        ""<hoop_white>"": [""in(<peg_green>)"", ""above(<hoop_purple>)""],
        //        ""<hoop_purple>"": [""in(<peg_green>)""],
        //        ""<peg_red>"": [],
        //        ""<peg_blue>"": []
        //    },
        //    ""your_explanation"": ""I included three hoops (yellow, white, purple) that are on the green peg, along with two additional pegs (red and blue). Each hoop is in the green peg, and the yellow hoop is above the white, which is above the purple, showing their stacked order. There are no other objects in the scene.""
        //}";

        string state_description = main.stateDescription;

        //if (sceneDescriptionJSON == "")
        //{
        //    Debug.Log("[StateDescriptor] -- Please ensure sceneDescriptor is called first");
        //    yield break;
        //}

        string previous_feedback = main.innerbot_feedback;

        Debug.Log("[StateDescriptor] Previous state description:" + state_description);
        Debug.Log("[StateDescriptor] Previous feedback:" + previous_feedback);

        string prompt = promptTemplate
                    .Replace("{scene_description}", sceneDescriptionJSON)
                    .Replace("{user_instruction}", userInstruction)
                    .Replace("{predicates_description}", predicates_description)
                    .Replace("{state_description}", state_description)
                    .Replace("{previous_feedback}", previous_feedback);

        //StartCoroutine(CallDeepSeekAPI(prompt));
        // yield return StartCoroutine(CallOpenAIAPI(prompt));
        // string imagePath = Path.Combine(Application.dataPath, $"Tasks/PegTransferTask/Task_Images/SceneImage_{main.imageCounter}.png");
        // yield return StartCoroutine(GenerateCombinedDescription(imagePath, prompt));

        yield return StartCoroutine(CallGeminiAPI(prompt));
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

        // main.stateDescription = @"
        //     {
        //         ""goal_spatial_relations"": {
        //             ""yellow_hoop"": [""in(<blue_pillar>)""],
        //             ""purple_hoop"": [""in(<blue_pillar>)"", ""above(<yellow_hoop>)""],
        //             ""white_hoop"": [""in(<blue_pillar>)"", ""above(<purple_hoop>)""]
        //         },
        //         ""constraint_spatial_relations"": {
        //             ""purple_hoop"": [""NOT(above(<white_hoop>)) OR in(<green_pillar>)""],
        //             ""yellow_hoop"": [
        //             ""NOT(above(<purple_hoop>)) OR in(<green_pillar>)"",
        //             ""NOT(above(<white_hoop>)) OR in(<green_pillar>)""
        //             ]
        //         }
        //     }
        // ";
        // output = main.stateDescription;
        // yield break;
    }

  IEnumerator CallGeminiAPI(string prompt)
{
    string APIKey = main.getGeminiAPIKey();
    string APIurl = main.getGeminiAPIUrl();

    // Escape prompt string for JSON
    string escapedPrompt = prompt.Replace("\\", "\\\\")
                                 .Replace("\"", "\\\"")
                                 .Replace("\n", "\\n")
                                 .Replace("\r", "\\r");

    // Build JSON request body (Gemini)
    string jsonRequest = $@"{{
        ""contents"": [
            {{
                ""role"": ""user"",
                ""parts"": [
                    {{ ""text"": ""As a state representation VLM, you will be given user instructions on a task."" }}
                ]
            }},
            {{
                ""role"": ""user"",
                ""parts"": [
                    {{ ""text"": ""{escapedPrompt}"" }}
                ]
            }}
        ],
        ""generationConfig"": {{
                ""temperature"": 0.0
            }}
    }}";

    UnityWebRequest request = new UnityWebRequest(APIurl, "POST");
    byte[] bodyRaw = System.Text.Encoding.UTF8.GetBytes(jsonRequest);
    request.uploadHandler = new UploadHandlerRaw(bodyRaw);
    request.downloadHandler = new DownloadHandlerBuffer();

    request.SetRequestHeader("Content-Type", "application/json");
    request.SetRequestHeader("x-goog-api-key", APIKey);

    Debug.Log("[StateDescriptor] Sending Gemini API Request...");
    yield return request.SendWebRequest();
    Debug.Log("[StateDescriptor] Received API Response.");

    if (request.result != UnityWebRequest.Result.Success)
    {
        Debug.LogError($"[StateDescriptor] API Request Failed: {request.error}\n{request.downloadHandler.text}");
    }
    else
    {
        string jsonResponse = request.downloadHandler.text;

        Debug.Log("[StateDescriptor] Raw API response:\n" + jsonResponse);

        // Extract between flags directly from raw response JSON
        const string startFlag = "```start_flag";
        const string endFlag = "```end_flag";

        int s = jsonResponse.IndexOf(startFlag, StringComparison.OrdinalIgnoreCase);
        if (s < 0)
        {
            Debug.LogError("[StateDescriptor] start_flag not found in Gemini response.");
            yield break;
        }

        int contentStart = s + startFlag.Length;

        int e = jsonResponse.IndexOf(endFlag, contentStart, StringComparison.OrdinalIgnoreCase);
        if (e < 0)
        {
            Debug.LogError("[StateDescriptor] end_flag not found in Gemini response.");
            yield break;
        }

        string between = jsonResponse.Substring(contentStart, e - contentStart);

        // Unescape common JSON escapes (because we sliced from inside JSON string)
        output = between
            .Replace("\\n", "\n")
            .Replace("\\r", "\r")
            .Replace("\\t", "\t")
            .Replace("\\\"", "\"")
            .Replace("\\\\", "\\")
            .Trim();

        if (output.StartsWith("\n")) output = output.Substring(1).Trim();

        if (string.IsNullOrEmpty(output))
        {
            Debug.LogError("[StateDescriptor] Extracted output between flags is empty.");
            yield break;
        }

        Debug.Log("[StateDescriptor] Gemini Output:\n" + output);

        // Mimic original behavior: extract between flags (OpenAI version did this)
        // Here output is already extracted, so we keep the same downstream flow.
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

    // Add to existing StateDescriptor class
    public IEnumerator GenerateCombinedDescription(string imagePath, string prompt)
    {
        // 1. Load the image from file
        if (!File.Exists(imagePath))
        {
            Debug.LogError($"[CombinedDescriptor] Image file not found: {imagePath}");
            yield break;
        }

        byte[] imageData = File.ReadAllBytes(imagePath);
        string base64Image = Convert.ToBase64String(imageData);
        Debug.Log($"[CombinedDescriptor] Loaded image from {imagePath}");

        // 2. Prepare API credentials
        string APIKey = main.getOpenAIAPIKey();
        string APIurl = main.getOpenAIReasoningURL();  // Using reasoning URL for multimodal

        // 3. Combine both prompts into one
        // Start with scene descriptor prompt
        string combinedSystemPrompt = sceneDescriptor.systemPrompt +
            "\n\nAfter generating the scene JSON above, please also generate a state descriptor using the following instructions:\n" +
            prompt +
            "\n\nReturn a result as fast as possible.";

        // Replace all placeholders in combined prompt
        combinedSystemPrompt = combinedSystemPrompt
            .Replace("{predicates_description}", predicates_description)
            .Replace("{valid_scene_definition}", sceneDescriptor.valid_scene_definition);

        string escapedSystem = combinedSystemPrompt
            .Replace("\\", "\\\\")
            .Replace("\"", "\\\"")
            .Replace("\n", "\\n")
            .Replace("\r", "\\r");

        // 4. Prepare the user prompt part
        string userPrompt = "For this image: 1) Generate the scene description JSON, then 2) Generate the state descriptor JSON based on that scene and the user instruction. Wrap the scene JSON in ```scene_start and ```scene_end flags, and the state descriptor in ```state_start and ```state_end flags.";
        string userInstructionText = $"User Instruction: {main.userInstruction}\nPrevious state: {(string.IsNullOrEmpty(main.stateDescription) ? "None" : main.stateDescription)}\nPrevious feedback: {(string.IsNullOrEmpty(main.innerbot_feedback) ? "None" : main.innerbot_feedback)}";

        string escapedPrompt = userPrompt
            .Replace("\\", "\\\\")
            .Replace("\"", "\\\"")
            .Replace("\n", "\\n")
            .Replace("\r", "\\r");

        string escapedUserContext = userInstructionText
            .Replace("\\", "\\\\")
            .Replace("\"", "\\\"")
            .Replace("\n", "\\n")
            .Replace("\r", "\\r");

        // 5. Assemble request body with both text and image
        string jsonRequest = $@"{{
            ""model"": ""o1"",
            ""input"": [
                {{
                    ""role"": ""system"",
                    ""content"": ""{escapedSystem}""
                }},
                {{
                    ""role"": ""user"",
                    ""content"": [
                        {{
                            ""type"": ""input_text"",
                            ""text"": ""{escapedPrompt}""
                        }},
                        {{
                            ""type"": ""input_text"",
                            ""text"": ""{escapedUserContext}""
                        }},
                        {{
                            ""type"": ""input_image"",
                            ""image_url"": ""data:image/png;base64,{base64Image}""
                        }}
                    ]
                }}
            ]
        }}";

        // 6. Send request
        UnityWebRequest request = new UnityWebRequest(APIurl, "POST");
        byte[] bodyRaw = System.Text.Encoding.UTF8.GetBytes(jsonRequest);
        request.uploadHandler = new UploadHandlerRaw(bodyRaw);
        request.downloadHandler = new DownloadHandlerBuffer();
        request.SetRequestHeader("Content-Type", "application/json");
        request.SetRequestHeader("Authorization", $"Bearer {APIKey}");

        Debug.Log("[CombinedDescriptor] Sending API Request...");
        yield return request.SendWebRequest();
        Debug.Log("[CombinedDescriptor] Received API Response.");

        // 7. Process response
        if (request.result != UnityWebRequest.Result.Success)
        {
            Debug.LogError($"[CombinedDescriptor] API Request Failed: {request.error}\n{request.downloadHandler.text}");
            yield break;
        }

        string jsonResponse = request.downloadHandler.text;

        // Parse using the ResponsesAPIResponse class from SceneDescriptor
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
            Debug.LogError("[CombinedDescriptor] No valid message block in response.");
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
            Debug.LogError("[CombinedDescriptor] No output_text found!");
            yield break;
        }

        // 8. Extract both results and store in appropriate variables
        string fullOutput = outputText.Trim();
        Debug.Log("[CombinedDescriptor] Full output:\n" + fullOutput);

        // Extract scene JSON using scene_start/scene_end flags
        string sceneJSON = main.ExtractBetweenFlags(fullOutput, "scene_start", "scene_end");
        Debug.Log("[CombinedDescriptor] SCENE JSON: " + sceneJSON);
        if (!string.IsNullOrEmpty(sceneJSON))
        {
            Debug.Log("[CombinedDescriptor] Successfully extracted scene JSON");
            sceneDescriptor.output = sceneJSON;

            if (string.IsNullOrEmpty(main.initialSceneDesc))
                main.initialSceneDesc = sceneJSON;
        }
        else
        {
            Debug.LogError("[CombinedDescriptor] Failed to extract scene JSON");
        }

        // Extract state JSON using state_start/state_end flags
        string stateJSON = main.ExtractBetweenFlags(fullOutput, "state_start", "state_end");
        Debug.Log("[CombinedDescriptor] STATE JSON: " + stateJSON);
        if (!string.IsNullOrEmpty(stateJSON))
        {
            Debug.Log("[CombinedDescriptor] Successfully extracted state JSON");
            output = stateJSON;
            main.stateDescription = stateJSON;

            // Extract environment constraints
            string extracted_env_constraint = main.ExtractConstraintSpatialRelations(stateJSON);
            Debug.Log("[CombinedDescriptor] Extracted constraints: " + extracted_env_constraint);
            main.envConstraint = extracted_env_constraint;

            if (string.IsNullOrEmpty(main.initialStateDesc))
                main.initialStateDesc = stateJSON;
        }
        else
        {
            Debug.LogError("[CombinedDescriptor] Failed to extract state JSON");
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

    //IEnumerator CallDeepSeekAPI(string promptContent)
    //{
    //    string apiKey = main.getAPIKey();
    //    string apiUrl = main.getAPIURL();

    //    // Inline escaping for JSON compatibility
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
    //        ""max_tokens"": 1000
    //    }}";

    //    UnityWebRequest request = new UnityWebRequest(apiUrl, "POST");
    //    byte[] bodyRaw = System.Text.Encoding.UTF8.GetBytes(jsonRequest);
    //    request.uploadHandler = new UploadHandlerRaw(bodyRaw);
    //    request.downloadHandler = new DownloadHandlerBuffer();
    //    request.SetRequestHeader("Content-Type", "application/json");
    //    request.SetRequestHeader("Authorization", $"Bearer {apiKey}");

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
    //            Debug.Log("<color=green>--------- DeepSeek State Output ---------</color>\n" + output);
    //        }
    //        else
    //        {
    //            Debug.LogError("DeepSeek Reasoner returned empty result or malformed response.");
    //        }
    //    }
    //}

    //// Response wrappers for JsonUtility
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
