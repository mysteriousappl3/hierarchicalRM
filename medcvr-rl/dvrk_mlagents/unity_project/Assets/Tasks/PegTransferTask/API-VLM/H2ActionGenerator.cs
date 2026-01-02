using UnityEngine;
using UnityEngine.Networking;
using System.Collections;
using System.Text;
using System;

public class H2ActionGenerator : MonoBehaviour
{
    public SceneDescriptor sceneDescriptor;
    
    public H1ActionGenerator h1ActionGenerator;

    public Main main;

    public string output;
    public string promptTemplate;

    private void Start()
    {
        output = "";

        promptTemplate = @"
            Here is the scene description for a task in JSON format.

            {scene_description}

            Here are the H1 level function(s):

            {h1_actions}

            We plan to use VLMs for long-horizon planning of complex tasks and thus want to come up with another higher hierarchy of function(s) to potentially shorten the number of function steps the planner has to use for completing a complex task.

            H2 level functions are ones that are composed of a sequence of H1 level function(s).
            Come up with this H2 hierarchy of function(s) in C# that do more complex operations for the kind of objects in the scene than the H1 level functions.
            Provide code where the body of any H2 function should only include calls to H1 level function(s).
            Ensure you also add a docstring for each of the function you generate with details on what the function does and what each parameter means clearly.
            These functions should be generic, i.e., should not specify any specific scene object.
            You are not allowed to create any helper functions or assume or define any variables in the function body. Add as input anything you think is needed.

            Generate as many H2 functions as you can, but ensure each function is meaningful and logically correct.
            By meaningful, make sure every H2 function has a clear purpose and is not just a combination of H1 functions without a logical flow.
            Also, do NOT create H2 functions that repeat calling the same H1 function with the same parameters.

            Make sure to wrap all the function definitions within a ```start_flag and ```end_flag for parsing purposes.
            Only give the function definition without wrapping it inside any class.
            Assume the functions take string inputs.

            Additionally, make sure to represent each H2 function to its sequence of H1 functions with its parameters as comma separated of the format.
            If multiple function definitions exit, repsent each mapping by comma separated. Only include the function signature and any parameters as strings in this.
            The format is given below:

            H2_function() = [H1_func1(), H1_func2(), H1_func3()].

            It is important to remember that in the function call signature, any parameters that are not used in the function should be removed.
            Also, ensure the H1 functions called have the correct parameters as specified in the H1 function signatures.

            Wrap all the mapping comma separated in tag ```start_mapping and ```end_mapping flags for parsing purposes.
            ";

    }


    public IEnumerator generateH2Actions()
    {
        string h1Actions = h1ActionGenerator.output;

        if (h1Actions == "")
        {
            Debug.Log("[H2ActionGenerator] -- Please call H1 Action generator first!");
            yield break;
        }
        string sceneDescriptionJSON = sceneDescriptor.output;

        if (sceneDescriptor.output == "")
        {
           Debug.Log("[SceneDescriptor] -- Please ensure you generate an output from scene descriptor VLM by calling generate()");
           yield break;
        }


        //// [TODO] - Example scene_description. Remove when using OpenAI API
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

        //// TODO: Remove later this dummy h1Actions function
        //h1Actions = @"
        //    public void transfer_ring(string source_peg, string destination_peg)
        //    {
        //        Move(source_peg);
        //        Grab();
        //        Move(destination_peg);
        //        Drop();
        //    }
        //    ";

        string prompt = promptTemplate
            .Replace("{scene_description}", sceneDescriptionJSON)
            .Replace("{h1_actions}", h1Actions)
            ;


        // StartCoroutine(CallDeepSeekAPI(prompt));

        // yield return StartCoroutine(CallOpenAIAPI(prompt));
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
                    ""content"": ""You are an action generator VLM at a hierarchy level of H2 for given user instruction.""
                }},
                {{
                    ""role"": ""user"",
                    ""content"": ""{escapedPrompt}""
                }}
            ],
            ""reasoning_effort"": ""high"",
            ""max_completion_tokens"": 50000
        }}";

        UnityWebRequest request = new UnityWebRequest(APIurl, "POST");
        byte[] bodyRaw = System.Text.Encoding.UTF8.GetBytes(jsonRequest);
        request.uploadHandler = new UploadHandlerRaw(bodyRaw);
        request.downloadHandler = new DownloadHandlerBuffer();

        request.SetRequestHeader("Content-Type", "application/json");
        request.SetRequestHeader("Authorization", $"Bearer {APIKey}");

        Debug.Log("[H2ActionGenerator] Sending OpenAI API Request...");
        yield return request.SendWebRequest();
        Debug.Log("[H2ActionGenerator] Received API Response.");

        if (request.result != UnityWebRequest.Result.Success)
        {
            Debug.LogError($"[H2ActionGenerator] API Request Failed: {request.error}\n{request.downloadHandler.text}");
        }
        else
        {
            string jsonResponse = request.downloadHandler.text;

            OpenAIResponse response = JsonUtility.FromJson<OpenAIResponse>(jsonResponse);

            Debug.Log("[H2ActionGen] Raw API response:\n" + jsonResponse);

            if (response.choices != null && response.choices.Length > 0)
            {
                string content_output = response.choices[0].message.content.Trim();
                Debug.Log("[H2ActionGenerator] OpenAI Output:\n" + content_output);
                output = main.ExtractBetweenFlags(content_output);
                Debug.Log("EXTRACTED DATA ");
                Debug.Log(output);

                string functionMappingLine = main.ExtractBetweenFlags(content_output, "```start_mapping", "```end_mapping");
                // main.h2Toh1Mapping = main.ParseFunctionMappings(functionMappingLine);
                Debug.Log("H2 FUNC MAPPING LINE - " + functionMappingLine);
                main.ParseHierarchicalFunctionMappings(functionMappingLine);

                // H1 → H0
                Debug.Log("======== H1 to H0 Mapping ========");
                foreach (var kv in main.h1Toh0Mapping)
                {
                    Debug.Log($"H1: {kv.Key} => H0 Calls: [{string.Join(", ", kv.Value)}]");
                }

                // H2 → H1
                Debug.Log("======== H2 to H1 Mapping ========");
                foreach (var kv in main.h2Toh1Mapping)
                {
                    Debug.Log($"H2: {kv.Key} => H1 Calls: [{string.Join(", ", kv.Value)}]");
                }

                // Function Param Signatures
                Debug.Log("======== Function Param Signatures ========");
                foreach (var kv in main.functionParamSignature)
                {
                    Debug.Log($"{kv.Key} params: ({string.Join(", ", kv.Value)})");
                }

                // Full Calls With Args
                Debug.Log("======== Calls With Args ========");
                foreach (var kv in main.functionToCallsWithArgs)
                {
                    Debug.Log($"{kv.Key} => [{string.Join(", ", kv.Value)}]");
                }
            }
            else
            {
                Debug.LogError("[H2ActionGenerator] OpenAI API returned empty choices or malformed response.");
            }
        }
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
                    {{ ""text"": ""You are an action generator VLM at a hierarchy level of H2 for given user instruction."" }}
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

    Debug.Log("[H2ActionGenerator] Sending Gemini API Request...");
    yield return request.SendWebRequest();
    Debug.Log("[H2ActionGenerator] Received API Response.");

    if (request.result != UnityWebRequest.Result.Success)
    {
        Debug.LogError($"[H2ActionGenerator] API Request Failed: {request.error}\n{request.downloadHandler.text}");
    }
    else
    {
        string jsonResponse = request.downloadHandler.text;

        Debug.Log("[H2ActionGen] Raw API response:\n" + jsonResponse);

        // Extract primary output between flags directly from raw response JSON
        const string startFlag = "```start_flag";
        const string endFlag = "```end_flag";

        int s = jsonResponse.IndexOf(startFlag, StringComparison.OrdinalIgnoreCase);
        if (s < 0)
        {
            Debug.LogError("[H2ActionGen] start_flag not found in Gemini response.");
            yield break;
        }

        int contentStart = s + startFlag.Length;

        int e = jsonResponse.IndexOf(endFlag, contentStart, StringComparison.OrdinalIgnoreCase);
        if (e < 0)
        {
            Debug.LogError("[H2ActionGen] end_flag not found in Gemini response.");
            yield break;
        }

        string between = jsonResponse.Substring(contentStart, e - contentStart);

        // Unescape common JSON escapes (because we sliced from inside JSON string)
        string content_output = between
            .Replace("\\n", "\n")
            .Replace("\\r", "\r")
            .Replace("\\t", "\t")
            .Replace("\\\"", "\"")
            .Replace("\\\\", "\\")
            .Trim();

        if (content_output.StartsWith("\n")) content_output = content_output.Substring(1).Trim();

        if (string.IsNullOrEmpty(content_output))
        {
            Debug.LogError("[H2ActionGen] Extracted output between flags is empty.");
            yield break;
        }

        Debug.Log("[H2ActionGenerator] Gemini Output:\n" + content_output);

        output = content_output;

        Debug.Log("EXTRACTED DATA ");
        Debug.Log(output);

        // Extract mapping block between mapping flags (from raw response)
        const string startMapping = "```start_mapping";
        const string endMapping = "```end_mapping";

        int ms = jsonResponse.IndexOf(startMapping, StringComparison.OrdinalIgnoreCase);
        if (ms >= 0)
        {
            int mStart = ms + startMapping.Length;
            int me = jsonResponse.IndexOf(endMapping, mStart, StringComparison.OrdinalIgnoreCase);
            if (me >= 0)
            {
                string mappingBetween = jsonResponse.Substring(mStart, me - mStart);

                string functionMappingLine = mappingBetween
                    .Replace("\\n", "\n")
                    .Replace("\\r", "\r")
                    .Replace("\\t", "\t")
                    .Replace("\\\"", "\"")
                    .Replace("\\\\", "\\")
                    .Trim();

                if (functionMappingLine.StartsWith("\n")) functionMappingLine = functionMappingLine.Substring(1).Trim();

                Debug.Log("H2 FUNC MAPPING LINE - " + functionMappingLine);
                main.ParseHierarchicalFunctionMappings(functionMappingLine);
            }
            else
            {
                Debug.LogError("[H2ActionGen] end_mapping not found in Gemini response.");
            }
        }
        else
        {
            Debug.LogError("[H2ActionGen] start_mapping not found in Gemini response.");
        }

        // H1 → H0
        Debug.Log("======== H1 to H0 Mapping ========");
        foreach (var kv in main.h1Toh0Mapping)
        {
            Debug.Log($"H1: {kv.Key} => H0 Calls: [{string.Join(", ", kv.Value)}]");
        }

        // H2 → H1
        Debug.Log("======== H2 to H1 Mapping ========");
        foreach (var kv in main.h2Toh1Mapping)
        {
            Debug.Log($"H2: {kv.Key} => H1 Calls: [{string.Join(", ", kv.Value)}]");
        }

        // Function Param Signatures
        Debug.Log("======== Function Param Signatures ========");
        foreach (var kv in main.functionParamSignature)
        {
            Debug.Log($"{kv.Key} params: ({string.Join(", ", kv.Value)})");
        }

        // Full Calls With Args
        Debug.Log("======== Calls With Args ========");
        foreach (var kv in main.functionToCallsWithArgs)
        {
            Debug.Log($"{kv.Key} => [{string.Join(", ", kv.Value)}]");
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
