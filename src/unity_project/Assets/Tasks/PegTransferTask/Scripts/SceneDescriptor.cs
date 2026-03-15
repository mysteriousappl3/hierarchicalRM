using UnityEngine;
using UnityEngine.Networking;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System;

public class SceneDescriptor : MonoBehaviour
{
    [SerializeField]
    private Texture2D sceneImage;
    private Texture2D refImage;

    public Main main;

    public string systemPrompt;
    public string predicates_description;
    public string valid_scene_definition;

    public string output;

    public string lastResponseId = "";

    void Start()
    {
        systemPrompt = @"
            Understand this scene and generate a scenery description based on the given scene. If the object specified in the user instruction
            does NOT exist, say what object is not found in the scene.
            Information about environments is given as python dictionary. For example:
            {
                ""objects"": […],
                ""object_properties"": {
                    ""<object_name>"": [property1, property2, …], …},
                ""spatial_relations"": {
                    ""<object1_name>"": [""predicate1(<object2_name>)"", ""predicate2(…)"", …], …},
                ""your_explanation"": ""…""
            }

            - The ""objects"" field denotes the list of objects. Enclose the object names with '<' and '>'. Connect the words without spaces, using underscores instead. Make sure each object is uniquely identified and through the object name it can be clearly understood which object its name refers to.
            - The ""object_properties"" field denotes the properties of the objects. Objects have the following properties. ONLY use the following properties:
                - GRABBABLE: If an object has this attribute, it can be potentially grabbed and moved by the robot.
                - REACHABLE: If an object has this attribute, this object is stationary and the robot can move to but cannot move this object.
            - The “spatial_relations” field denotes the list of relationships between objects. Use only the following functions to describe these relations. [A, B] means A AND B and you may use (A OR B) and NOT A to indicate disjunction and negation. Make sure your predicate only contains object names as parameters.
              {predicates_description}
            - Explain what you included and what you omitted and why in the ""your_explanation"" field.

            
            Please remember to always specify the spacial relations for each interactable object in the scene to accurately capture the current state of the scene.
            Please be consistent with the color of the objects in your scene representation JSON.

            Here is the definition of a valid scene:
            {valid_scene_definition}

            If the input image scene is not valid, don't return a JSON and only return a field VALID: with value NO.

            If the scene is valid, only return the JSON.

            Make sure to wrap the response definition within a ```start_flag and ```end_flag for parsing purposes.
        ";

        valid_scene_definition = "A valid scene is one where all the hoops are inside a peg (pillar), not necessarily all inside the same peg (pillar). An example of invalid state might be any hoop outside a peg";

        predicates_description = "Here are the predicates to be used: [in(), above()].\nFor example, ‘in(<obj_1>)’ indicates that an object is in obj_1 and ‘above(<obj_2>)’ means an object is DIRECTLY above obj_2 and there are no objects between them.";
    }

    public IEnumerator generateSceneDescription()
    {
        string filePath = Path.Combine(Application.dataPath, $"Tasks/PegTransferTask/Task_Images/SceneImage_{main.imageCounter}.png");

        if (File.Exists(filePath))
        {
            byte[] imageData = File.ReadAllBytes(filePath);

            Texture2D texture = new Texture2D(2, 2);
            if (texture.LoadImage(imageData))
            {
                Debug.Log("Successfully loaded image into Texture2D");
                sceneImage = texture;
            }
            else
            {
                Debug.LogError("Failed to load image data into texture.");
                yield break;
            }
        }
        else
        {
            Debug.LogError("Image file not found: " + filePath);
        }

        if (sceneImage == null)
        {
            Debug.LogError("[SceneDescriptor] -- Please ensure to capture a screenshot of the scene.");
            yield break;
        }


        string prompt = "For the given input image, please follow the system prompt to generate the scene description JSON.";
        yield return StartCoroutine(CallOpenAIAPI(prompt, sceneImage));

    }

    IEnumerator CallOpenAIAPI(string promptContent, Texture2D image)
    {
        string APIKey = main.getOpenAIAPIKey();
        string APIurl = main.getOpenAIReasoningURL();  // should be: https://api.openai.com/v1/responses

        // Convert image to Base64
        byte[] imageBytes = image.EncodeToPNG();
        string base64Image = System.Convert.ToBase64String(imageBytes);

        // Escape prompt content
        string escapedPrompt = promptContent
            .Replace("\\", "\\\\")
            .Replace("\"", "\\\"")
            .Replace("\n", "\\n")
            .Replace("\r", "\\r");

       
        List<string> inputParts = new List<string>();

        if (string.IsNullOrEmpty(lastResponseId))
        {
            systemPrompt = systemPrompt
                .Replace("{predicates_description}", predicates_description)
                .Replace("{valid_scene_definition}", valid_scene_definition);

            string escapedSystem = systemPrompt
                .Replace("\\", "\\\\")
                .Replace("\"", "\\\"")
                .Replace("\n", "\\n")
                .Replace("\r", "\\r"); 

            inputParts.Add($@"{{
                ""role"": ""system"",
                ""content"": ""{escapedSystem}""
            }}");
        }

        // Always include user+image
        inputParts.Add($@"{{
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
        }}");

        // Join safely
        string inputBlock = string.Join(",\n", inputParts);

        // Add prevId part (outside input array)
        string prevIdPart = string.IsNullOrEmpty(lastResponseId)
            ? ""
            : $",\n  \"previous_response_id\": \"{lastResponseId}\"";

        // Final JSON
        string jsonRequest = $@"{{
        ""model"": ""o1"",
        ""input"": [
            {inputBlock}
        ]{prevIdPart}
        }}";


        // Send request
        UnityWebRequest request = new UnityWebRequest(APIurl, "POST");
        byte[] bodyRaw = Encoding.UTF8.GetBytes(jsonRequest);
        request.uploadHandler = new UploadHandlerRaw(bodyRaw);
        request.downloadHandler = new DownloadHandlerBuffer();
        request.SetRequestHeader("Content-Type", "application/json");
        request.SetRequestHeader("Authorization", $"Bearer {APIKey}");

        Debug.Log("[SceneAnalyzerVLM] Sending OpenAI Responses API Request...");
        yield return request.SendWebRequest();
        Debug.Log("[SceneAnalyzerVLM] Received API Response.");

        if (request.result != UnityWebRequest.Result.Success)
        {
            Debug.LogError($"[SceneAnalyzerVLM] API Request Failed: {request.error}\n{request.downloadHandler.text}");
            yield break;
        }

        string jsonResponse = request.downloadHandler.text;
        Debug.Log("[SceneAnalyzerVLM] Raw API response:\n" + jsonResponse);

        // Parse using your defined classes
        ResponsesAPIResponse response = JsonUtility.FromJson<ResponsesAPIResponse>(jsonResponse);
        lastResponseId = response.id;

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
            Debug.LogError("[SceneAnalyzerVLM] No valid message block in response.");
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
            Debug.LogError("[SceneAnalyzerVLM] No output_text found!");
            yield break;
        }

        output = outputText.Trim();

        if (output.Contains("NO"))
        {
            yield break;
        }

        string sceneValidityResponse = main.ExtractBetweenFlags(output);

        Debug.Log("SCENE VALIDITY = " + sceneValidityResponse);
        output = main.ExtractBetweenFlags(output);

        if (string.IsNullOrEmpty(main.initialSceneDesc))
        {
            main.initialSceneDesc = output;
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
        public string type;
        public string text;
    }
}
